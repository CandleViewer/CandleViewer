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
   its class names as a view-as frame leads its Hi-fi and Copy keys cells with it (G7); K9 no exit drawn gated (a frame, a
   section 2.4 cell, a prose paragraph or section 10.2; a bare Esc too), and K4 no confirm drawn while
   the summary loads (a frame row, a section 2.4 row or a prose paragraph naming the load read whole), each
   gated word (GATED_ADJ) read before its noun or after it (r4o: ", visible but inactive", "it"
   carrying the subject); K10 is gate 2 (``ac2.*``); K11 the compromise card's steps, keys and deck
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
7d. The security text, pinned default-deny (the orchestrator's text round 3): a clause of the spec
   or the hand-off (a heading, a table cell, a prose sentence, a fenced line) that names a key, a
   secret, a credential, a passphrase, private, a withdrawal / transfer word, any fund / funds /
   money word, a reveal or mask word, plain / clear text or "in clear", a token, a password, a
   balance, "shown in full", CMP-034 / CMP-175 / CMP-201, a full / whole / raw id, or the
   view-as leg is security-bearing (BEARING), and every one must equal, whitespace normalised and in
   document order, its entry of SEC_PIN_TXT (section, row and column or "prose", exact text). New,
   changed, moved or duplicated security text, and a pinned clause gone, FAIL ``sec-pin`` with its
   line: the word list decides which clauses are pinned, the table what they may say; a clause
   with none of its words is read by 7b / 7c only. ``--repin-security`` prints the table from the
   current text for a reviewer; the table is committed at the end of this file. 7b and 7c stay as
   additional gates.
7e. The confirm-look clauses, pinned default-deny (r12): a clause of the spec or the hand-off that
   pairs "confirm" (confirm, Confirm, [Confirm], the confirm button) with a gated look word
   (disabled, dimmed, greyed / grayed (out), inactive, inert, locked, held, unavailable), in either
   order and in any case, is a confirm-look clause (CONFIRM_LOOK), and every one must equal, in
   document order, its entry of CONFIRM_LOOK_PINS (section, row and column or "prose", exact
   text). New, changed, moved or duplicated confirm-look text, and a pinned clause gone, FAIL
   ``confirm-look`` with its line, so a confirm drawn dimmed or disabled in a paragraph that does
   not name the load fails too; ``k4.loading`` and ``k9.exit`` stay. ``--repin-confirm-look`` prints
   the table for a reviewer; ``--check`` never re-pins.
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
(sha256). The file on disk is never touched. K mutations count one FAIL of their own code among
the specific gates; 7d's pin refuses them too wherever they edit pinned text. Then 7d's own list:
each round-3 lens form twice (in a clause with no security word, and inside a pinned clause),
section 8's and 10.1's view-as leg cut and two hand-off placements, each one distinct FAIL
(``sec-pin``), and ten phrasings drawn (seeded) from a verb x object grid, each placed in a table
row and in a prose sentence and each refused by the pin. Then 7e's: the five confirm forms as a
sentence of their own in lower, Title and UPPER case, in section 2.4's "Documented, not forked"
paragraph and in section 7's keyboard paragraph (neither names the load), and a pinned confirm-look
paragraph moved and duplicated, each one distinct FAIL (``confirm-look``; the security pin's
``sec-pin`` beside it where the edit moves security text).

Usage: python3 -I -B docs/design/_tools/e27_d03_hifi_audit.py [--json] [--check] [--self-test]
       [--repin-security] [--repin-confirm-look]
Exit 1 on any gated FAIL (a plain run and ``--check``); ``--check`` also re-derives the markers;
WARNs never fail. UTF-8 stdout.
"""

from __future__ import annotations

import importlib.util
import json
import re
import string
import sys
import textwrap
from collections.abc import Callable
from difflib import SequenceMatcher
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
# K3 (r3o): a fund right in the modal form ("can withdraw", "may transfer", "is able to withdraw")
WITHDRAW_MODAL = re.compile(
    r"\b(?:can|may|could|might|will|able +to)\s+(?:also\s+|still\s+)?(?:withdraw|transfer)\w*",
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
# K1: a control that shows or copies key material, or a key id longer than `...` plus 4; r3o adds
# the view / toggle / expose verbs and a visibility toggle in either order
SHOW_MATERIAL = re.compile(
    r"\[(?:Show|Hide|Reveal|Unmask|View)\b[^\]]*\]|\[Copy\b[^\]]*\b(?:key|secret)\b[^\]]*\]"
    r"|\.\.\.[A-Za-z0-9]{4} *\[Copy\]"
    r"|\b(?:show|reveal|copy|unmask|display|view|toggle|expose)(?:s|ed|ing|d)? +"
    r"(?:the +|its +|a +)?(?:full +|whole +|plaintext +|raw +|complete +|entire +)?(?:API +)?"
    r"(?:key|secret)s?\b(?! (?:id|list|row|step|vault|screen|page))"
    r"|\btoggl(?:e|es|ed|ing) +(?:the +|its +)?(?:[\w']+ +){0,2}?visibility\b"
    r"|\bvisibility +(?:toggle|switch|control|button)s?\b"
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
# K4 / K9 (r4o): the gated-control vocabulary, read on either side of its noun
GATED_ADJ = (
    r"(?:`?aria-disabled`?|disabled|dimmed|gr[ea]yed(?:[- ]out)?|inactive|inert|locked|held"
    r"|hidden|unavailable|unusable|suppressed|no[- ]effect|gated)"
)
# K9: an exit drawn gated - after the exit (in its parentheses, after a verb, after a comma or an
# appositive of up to two words such as ", visible but inactive", or carried by "it" / "which"
# later in the sentence) or before it ("a disabled [Cancel]", "the greyed-out Close"); r4o fix: a
# bare Esc in any case, and Cancel before its gated word in any case (Close and Back there in Title
# or UPPER case only, so "held back" and "close to" stay prose)
GATE_WORD = r"(?:in the validity look|T2\b|led by the `lock`|" + GATED_ADJ + r"\b)"
EXIT_NOUN = r"(?:\[(?:Cancel|Close(?: card)?|Back)\]|\b(?:Cancel|Close|Back|Esc)\b|`Esc`)"
EXIT_AFTER_GATE = (
    r"(?:\[(?:Cancel|Close(?: card)?|Back)\]|\b(?:Cancel|Esc)\b|`Esc`"
    r"|(?-i:\b(?:Close|CLOSE|Back|BACK)\b))"
)
EXIT_GATED = re.compile(
    EXIT_NOUN + rf"(?: *\([^)]*?{GATE_WORD}[^)]*\)|(?: *\([^)]*\))? *"
    r"(?:(?:is|stays|becomes|remains|has|drawn|shown|rendered|visible|present)(?: +but)? +){0,2}"
    rf"{GATE_WORD}|(?: *\([^)]*\))?(?: +[a-z]+)?, +(?:[a-z]+ +){{0,2}}{GATE_WORD}"
    rf"|(?:(?!confirm)[^.|])*?[;(—] *(?:it|which)\b +(?:(?:is|stays|becomes|remains|has|drawn)(?: +but)? +){{0,2}}"
    rf"{GATE_WORD})"
    rf"|\b{GATED_ADJ}(?:,? +(?:and +|or +)?[\w-]+){{0,2}}?,? +{EXIT_AFTER_GATE}",
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
# K4: while the consequence summary loads the confirm is not in the DOM - never drawn disabled.
# r4o: a gated or drawn word after the confirm anywhere in the sentence (across ";", " — ", cells
# and parentheses, so "it" carries the subject), or a gated word before it ("a disabled confirm",
# "a greyed-out confirm", "a dimmed, inert confirm")
CONFIRM_NOUN = re.compile(r"(?<!\bto )\[?\bconfirm\b", re.IGNORECASE)
CONFIRM_STATE = re.compile(
    rf"(?<![\w-]){GATED_ADJ}(?![\w-])|\b(?:rendered|drawn|shown|visible|present)\b", re.IGNORECASE
)
CONFIRM_BEFORE = re.compile(
    rf"(?<![\w-]){GATED_ADJ}(?:,? +(?:and +|or +|but +)?[\w-]+){{0,2}}?,? +\[?confirm\b",
    re.IGNORECASE,
)
UNIT_END = re.compile(r"(?<=[.!?])\s+")
# "the native `disabled`" named as what a form replaces, and "a disabled confirm is not ..." denied
INSTEAD_BEFORE = re.compile(
    r"\b(?:in place of|instead of|rather than)(?:\s+[^\s,;]+){0,2}\s*`?$", re.IGNORECASE
)
NOT_AFTER = re.compile(r" +(?:is|are) +(?:not|never)\b", re.IGNORECASE)
LOADING_WORD = re.compile(r"\b(?:loading|loads|summary|Reading what)\b", re.IGNORECASE)
# r4o fix: where a sentence moves past the load ("after it, ...", "once the summary has loaded",
# "when the summary arrives"), the rest of it is the ready dialog (E42-D03's validity look, §10.3)
LOADED_CUE = re.compile(
    r"\b(?:after (?:it|that|the summary)\b|once (?:it|the summary)\b[^,;]*?\bloaded\b"
    r"|when the summary (?:arrives|has loaded)\b)",
    re.IGNORECASE,
)
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


def off_spans(raw: str, negate: bool = True, row_wide: bool = False) -> list[tuple[int, int]]:
    """K3: a withdrawal OFF (any case) without its verified time in its own string or item. With
    ``row_wide`` (§7c's table rows) a withdrawal or transfer word anywhere on the row ties the OFF
    to it, so a deck string cut to "off ✓" is read with its Where cell ("sign-off" is not one)."""
    spans: list[tuple[int, int]] = []
    row_names = row_wide and WITHDRAW_NEAR.search(raw) is not None
    at = 0
    for cell in raw.split("|"):
        for m in OFF_DRAWN.finditer(cell):
            if row_wide and cell[max(0, m.start() - 5) : m.start()].lower() == "sign-":
                continue
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
            near = row_names or WITHDRAW_NEAR.search(lead + seg) is not None
            if near and not VERIFIED_AT.search(seg):
                spans.append((at + m.start(), at + m.end()))
        at += len(cell) + 1
    return spans


def confirm_subject(before: str) -> bool:
    """K4: the confirm is the subject a later word describes - its last mention before the word is
    not denied ("no confirm") and no exit (K9's noun) stands between them."""
    last = [m for m in CONFIRM_NOUN.finditer(before) if not NEG_BEFORE.search(before[: m.start()])]
    return bool(last) and not re.search(EXIT_NOUN, before[last[-1].end() :])


def loading_confirm(text: str, whole: bool = False) -> list[str]:
    """K4: the confirm drawn present or disabled while the consequence summary loads. A sentence
    is read when it names the load; with ``whole`` (a frame row or a prose paragraph that names
    it) every sentence is, so a bare "A disabled confirm." on the loading frame fails. Each
    sentence is read up to its LOADED_CUE."""
    bad: list[str] = []
    loading = whole and LOADING_WORD.search(text) is not None
    for unit in UNIT_END.split(text):
        if not (loading or LOADING_WORD.search(unit)):
            continue
        if cue := LOADED_CUE.search(unit):
            unit = unit[: cue.start()]
        for m in CONFIRM_STATE.finditer(unit):
            if NEG_BEFORE.search(unit[: m.start()]) or INSTEAD_BEFORE.search(unit[: m.start()]):
                continue
            pre = CONFIRM_BEFORE.match(unit, m.start())
            if pre and NOT_AFTER.match(unit, pre.end()):
                continue
            if pre or confirm_subject(unit[: m.start()]):
                bad.append(unit[max(0, m.start() - 30) : m.end() + 20])
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


def prose_paragraphs(text: str) -> list[str]:
    """Every prose paragraph of ``text`` (outside fences, headings and tables; a blank line or a
    list item ends one), whitespace normalised."""
    out: list[str] = []
    para: list[str] = []
    fence = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            fence = not fence
        boundary = fence or not stripped or stripped.startswith(("```", "#", "|"))
        if boundary or LIST_ITEM.match(line):
            if para:
                out.append(" ".join(para))
            para = []
        if not boundary:
            para.append(" ".join(stripped.split()))
    if para:
        out.append(" ".join(para))
    return out


def prose_gate(spec: str, sec: dict[str, str], out: Out) -> None:
    """K4 / K9 (r4o fix) on the spec's prose: each paragraph that names the load read whole for the
    confirm, and every paragraph for a gated exit. §16 (the tool's own words, which quote the
    forms) and the revision line (to its paragraph's end) are not design text and are skipped."""
    body = spec.replace(sec.get("16", ""), "") if sec.get("16") else spec
    for para in [p.split("**Revision:**")[0] for p in prose_paragraphs(body)]:
        where = f"prose {para[:40]!r}"
        if shown := loading_confirm(para, whole=True):
            out.fail("k4.loading", f"{where} draws the confirm while the summary loads: {shown}")
        if gated := [m[0] for m in EXIT_GATED.finditer(para)]:
            out.fail("k9.exit", f"{where} draws an exit gated: {gated[:2]}")


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
        if shown := loading_confirm(raw, whole=True):
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
            by_name = VIEWAS_NAMED.search(f"{inv_names.get(n, '')} | {r['name']}") is not None
            if VIEWAS_NAMED.search(named) and any(h != ["rbac.view_as"] for h in heads):
                out.fail(
                    "k8.viewas",
                    f"{where} is a view-as frame (E27-D02 §7 or its class): its Hi-fi and Copy "
                    f"keys cells do not both lead with `rbac.view_as`: {heads}",
                )
            elif by_name and "view-as leg first" not in r["cls"]:
                out.fail(
                    "k8.viewas",
                    f"{where} is a view-as frame (E27-D02 §7): its class does not say "
                    f"'view-as leg first': {r['cls']!r}",
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
            joined = " | ".join(tr[i] for i in idx if i < len(tr))
            if shown := loading_confirm(joined, whole=True):
                out.fail(
                    "k4.loading", f"§2.4 {tr[0][:40]!r} draws the confirm while loading: {shown}"
                )
            if gated := [m[0] for m in EXIT_GATED.finditer(joined)]:
                out.fail("k9.exit", f"§2.4 {tr[0][:40]!r} draws an exit gated: {gated[:2]}")
    prose_gate(spec, sec, out)
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
    ("spec", 'form of "reveal" or "unmask",', 1),
    ("spec", '"reveal" or "unmask",', 1),
    ("spec", "withdrawal OFF, in any", 1),
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
    # r3o
    ("spec", "`false` reads OFF); none", 1),
    ("spec", "line, never OFF; cleared", 1),
    ("spec", "never OFF without", 1),
    ("spec", "never OFF (D4)", 1),
    ("spec", 'line: "Refused: this key can withdraw or transfer, and nothing', 1),
    ("spec", "never OFF (AD-3)", 1),
    ("spec", 'where "off" appears', 1),
    ("spec", "`aggregate`, never OFF · frame", 1),
    ("spec", '| "Refused: this key can withdraw or transfer, and nothing', 1),
    ("spec", "stored key can withdraw or transfer:", 1),
    ("spec", "state (“off” only", 1),
    ("spec", "(dash), never OFF · §2.1", 1),
    ("spec", "that can withdraw is", 1),
    ("spec", 'undated "OFF".** D02\'s', 1),
    ("spec", "says OFF without", 1),
    ("spec", 'N1: "OFF" without', 1),
    ("spec", '| "OFF" lives', 1),
    ("spec", "never OFF (served", 1),
    ("spec", "a `[Show]`, a", 1),
    ("spec", "(its `verified-off`, `verified-on`,", 1),
    ("spec", "never renders OFF; the", 1),
    ("spec", "an OFF in", 1),
    ("spec", 'form ("can withdraw"), with', 1),
    ("spec", "a secret, a visibility toggle, a bracketed", 1),
    ("spec", "view, copy or", 1),
    ("spec", '— "view the full key" and', 1),
    ("spec", '"toggle visibility" on', 1),
    ("spec", 'case), "can withdraw" on', 1),
    ("spec", "id, `[Show]` and", 1),
    ("spec", "and `[Copy]` on", 1),
    ("spec", "hand-off's CMP-033 row", 1),
    ("spec", 'id, "Can Withdraw", "view', 1),
    ("spec", '"view the full key")', 1),
    ("spec", "reveal word or", 1),
    ("spec", "a secret, a visibility toggle, a show", 1),
    ("spec", "or hide control,", 1),
    ("spec", "display, copy, toggle", 1),
    ("spec", "bracketed `[Show]`, `[View]`", 1),
    ("spec", 'form ("can withdraw", "may', 1),
    ("spec", 'withdraw", "may transfer",', 1),
    ("spec", "able to withdraw", 1),
    ("spec", "the OFF to", 1),
    ("spec", "the reveal words,", 1),
    ("spec", "a reveal or mask word", 2),
    ("hand-off", "`docs/design/_tools/e27_d03_hifi_audit.py`'s (spec §9).", 1),
    ("hand-off", "colours; no reveal, timer or", 1),
    ("hand-off", "timer or copy state exists", 1),
    ("hand-off", "`packages/ui/tokens` at `e8bca4bb7` (spec §2.3,", 1),
    ("hand-off", "draws a reveal meanwhile", 1),
    ("hand-off", "§2.3; no reveal, timer or", 1),
    ("hand-off", "timer or copy exists", 1),
)


# §7c: the egress IP cue (its placeholder too) and a bracketed control on any line
IP_CUE = re.compile(IP_WORD.pattern + r"|\{egress_ip\}", re.IGNORECASE)
BRACKET_CONTROL = re.compile(r"\[(?:Copy|Show|Hide|Reveal|Unmask|View)\b[^\]]*\]", re.IGNORECASE)


def git_sha_or_name(clause: str, m: re.Match[str]) -> bool:
    """A bare-id-shaped run that is a backticked git sha (9 or 40 characters) or a CamelCase story name
    (a capitalised word of four or more letters); only an uncued clause may carry one."""
    run = m[0]
    ticked = clause[m.start() - 1 : m.start()] == "`" and clause[m.end() : m.end() + 1] == "`"
    if ticked and re.fullmatch(r"[0-9a-f]{9}|[0-9a-f]{40}", run):
        return True
    return re.search(r"[A-Z][a-z]{3,}", run) is not None


def ip_copy(line: str, at: int) -> bool:
    """A bracketed control whose nearest cue before it on the line (else after it) is the egress
    IP: CMP-033's copy, the one copy control a key screen draws (D6, KV-I11)."""
    ip = [x.end() for x in IP_CUE.finditer(line[:at])]
    cue = [x.end() for x in FIELD_NAMED.finditer(line[:at])]
    if ip or cue:
        return max(ip, default=-1) > max(cue, default=-1)
    ip_a, cue_a = IP_CUE.search(line[at:]), FIELD_NAMED.search(line[at:])
    return ip_a is not None and (cue_a is None or ip_a.start() < cue_a.start())


def line_hits(
    line: str, frame_row: bool, field_heading: bool = False
) -> list[tuple[int, int, str]]:
    """Every security hit on one line: (start, end, code). A frame row is read here for the reveal
    words, the dated OFF and the modal fund right (the frame gate reads the rest). Every other line
    is read clause by clause for all five, with no cue: a bare id, a show / view / copy / toggle of
    a key or a secret, a bracketed control (unless it is the egress IP's copy) and a fund right. A
    clause that names a key or a secret field (or a row whose first cell or heading does) is also
    read for the long run, a toggle and a bare Copy, and its git-sha-shaped runs count as ids."""
    hits = [(m.start(), m.end(), "reveal") for m in DOC_REVEAL.finditer(line)]
    row = line.lstrip().startswith("|")
    hits += [(x, y, "k3.off") for x, y in off_spans(line, negate=False, row_wide=row)]
    hits += [(m.start(), m.end(), "k3.withdraw") for m in WITHDRAW_MODAL.finditer(line)]
    if frame_row:
        return hits
    first = cells(line)[0] if row else ""
    field_row = field_heading or FIELD_NAMED.search(first) is not None
    for a, b in clause_spans(line):
        clause = line[a:b]
        cued = field_row or FIELD_NAMED.search(clause) is not None
        ids = [
            (m.start(), m.end())
            for m in BARE_ID.finditer(clause)
            if cued or not git_sha_or_name(clause, m)
        ]
        ids += [
            (m.start(), m.end())
            for m in MASK_TAIL.finditer(clause)
            if m[1] or not (re.fullmatch(r"[A-Za-z0-9]{4}", m[2]) or m[2] == "{last4}")
        ]
        if cued:
            ids += [(m.start(), m.end()) for m in LONG_RUN.finditer(clause) if plaintext_like(m[0])]
        hits += [(a + x, a + y, "k1.masked") for x, y in ids]
        shown = [(m.start(), m.end()) for m in SHOW_MATERIAL.finditer(clause)]
        shown += [
            (m.start(), m.end())
            for m in BRACKET_CONTROL.finditer(clause)
            if not ip_copy(line, a + m.start())
        ]
        shown += [(m.start(), m.end()) for m in SHOW_CONTROL.finditer(clause)]
        if cued:
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


# --- 7d. the security text, pinned default-deny (the orchestrator's text round 3) ----------------
# A clause of the spec or the hand-off (a heading, a table cell, a prose sentence, a fenced line) is
# security-bearing when it names any of these, case-insensitive, at a word boundary, plurals and
# hyphenations included: a key, an API key or a key id, a secret, a credential, a passphrase,
# private, a withdrawal or transfer word, any fund / funds / money word (so a fund right in any
# phrasing: "can move funds", "funds can leave"), reveal or (un)mask, plain or clear text, "in clear",
# CMP-034 / CMP-175 / CMP-201 by number or name, a full / whole / raw id; and, pinned explicitly,
# a clause naming the view-as leg (section 8's and section 10.1's statements of the leg order).
BEARING = re.compile(
    r"\b(?:api[- ]?)?keys?(?:[- ]?ids?)?\b|\bsecrets?\b|\bcredentials?\b|\bpassphrases?\b"
    r"|\bprivate\b|\bwithdraw\w*|\btransfer\w*|\bfund(?:s|ed|ing)?\b|\bmoney\b"
    r"|\b(?:un-?)?(?:reveal|mask)\w*|\bunmask\w*|\b(?:plain|clear)[- ]?text\b"
    r"|\bin\s+(?:the\s+)?clear\b"
    r"|\bCMP-(?:034|175|201)\b|MaskedValue|PasswordField|KeyPermissionBadge"
    r"|\b(?:full|whole|complete|entire|raw|real|unmasked)\s+(?:\w+\s+)?ids?\b"
    r"|\bview[- ]as leg\b"
    r"|\btokens?\b|\bpasswords?\b|\bbalances?\b|\bshown\s+in\s+full\b",
    re.IGNORECASE,
)
# --- 7e. the confirm-look clauses, pinned default-deny (r12) ------------------------------------
# "confirm" (any case, bracketed or as "the confirm button") and a gated look word in one clause,
# either order: the post-load confirm's legitimate description (section 10.3, D03-C11, D03-C16)
# is pinned verbatim, and any other such clause fails wherever it stands
CONFIRM_LOOK_ADJ = (
    r"(?:disabled|dimmed|gr[ea]yed(?:[- ]out)?|inactive|inert|locked|held|unavailable)"
)
CONFIRM_LOOK = re.compile(
    rf"\bconfirm\b.*\b{CONFIRM_LOOK_ADJ}\b|\b{CONFIRM_LOOK_ADJ}\b.*\bconfirm\b", re.IGNORECASE
)
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
PIN_SEP = " ‖ "
PIN_WIDTH = 96
Clause = tuple[str, str, str, int]


def one_space(text: str) -> str:
    return " ".join(text.split())


def text_clauses(name: str, text: str) -> list[Clause]:
    """Every clause of one document as (section, where, text, line): a heading; each cell of a table
    row (where: the header's ordinal, or the row's first cell and the cell's column); each sentence
    of a prose paragraph (a blank line, a heading, a table or a list item ends one); each line of a
    fenced block. Whitespace is normalised; the section is its heading, cut at 48 characters."""
    out: list[Clause] = []
    section, seen = f"{name} preamble", {f"{name} preamble": 1}
    head: list[str] = []
    para: list[tuple[int, str]] = []
    state = {"fence": 0}

    def flush() -> None:
        joined = " ".join(one_space(x) for _n, x in para)
        starts, at = [], 0
        for num, x in para:
            starts.append((at, num))
            at += len(one_space(x)) + 1
        pos = 0
        for sentence in SENTENCE_END.split(joined) if para else []:
            pos = joined.find(sentence, pos)
            line = max(n for a, n in starts if a <= pos)
            out.append((section, "prose", sentence, line))
            pos += len(sentence)
        para.clear()

    lines = text.split("\n")
    for num, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            state["fence"] ^= 1
        elif state["fence"]:
            if stripped:
                out.append((section, "code", one_space(stripped), num))
        elif line.startswith("#"):
            flush()
            label = one_space(line.lstrip("#"))[:48].rstrip()
            seen[label] = seen.get(label, 0) + 1
            section = label if seen[label] == 1 else f"{label} #{seen[label]}"
            out.append((section, "heading", one_space(line), num))
        elif stripped.startswith("|"):
            flush()
            if SEPARATOR.match(stripped):
                continue
            row = cells(stripped)
            if not (num > 1 and lines[num - 2].strip().startswith("|")):
                head = row
                out += [(section, f"head {i}", one_space(c), num) for i, c in enumerate(row, 1)]
                continue
            rid = one_space(row[0])[:40].rstrip() if row else ""
            for i, cell in enumerate(row):
                column = one_space(head[i])[:24].rstrip() if i < len(head) else str(i + 1)
                out.append((section, f"row {rid}{PIN_SEP}{column}", one_space(cell), num))
        else:
            if not stripped or LIST_ITEM.match(line):
                flush()
            if stripped:
                para.append((num, stripped))
    flush()
    return out


def bearing_clauses(name: str, text: str, select: re.Pattern[str] = BEARING) -> list[Clause]:
    return [c for c in text_clauses(name, text) if select.search(c[2])]


def render_pins(spec: str, handoff: str, select: re.Pattern[str] = BEARING) -> str:
    """The pinned table as ``--repin-security`` prints it for review and SEC_PIN_TXT holds it: a
    ``§ doc ‖ section`` line per section, an ``@ where`` line per clause, its text wrapped (at
    spaces only, so the joined lines are the clause again) on lines indented two spaces."""
    lines: list[str] = []
    for name, text in (("spec", spec), ("hand-off", handoff)):
        last = ""
        for section, where, clause, _num in bearing_clauses(name, text, select):
            if section != last:
                lines.append(f"§ {name}{PIN_SEP}{section}")
                last = section
            lines.append(f"@ {where}")
            lines += [
                "  " + part
                for part in textwrap.wrap(
                    clause, PIN_WIDTH, break_long_words=False, break_on_hyphens=False
                )
            ]
    return "\n".join(lines)


def pin_rows(table: str) -> list[tuple[str, str, str, str]]:
    """SEC_PIN_TXT parsed: (doc, section, where, text) in document order."""
    rows: list[tuple[str, str, str, str]] = []
    doc, section, where = "", "", ""
    parts: list[str] = []
    for line in [*table.split("\n"), "@ end"]:
        if line.startswith(("§ ", "@ ")) and parts:
            rows.append((doc, section, where, " ".join(parts)))
            parts = []
        if line.startswith("§ "):
            doc, section = line[2:].split(PIN_SEP, 1)
        elif line.startswith("@ "):
            where = line[2:]
        elif line.startswith("  "):
            parts.append(line[2:])
    return rows


def clip(text: str, width: int = 72) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def pin_gate(
    spec: str,
    handoff: str,
    out: Out,
    table: str = "",
    select: re.Pattern[str] = BEARING,
    code: str = "sec-pin",
    kind: str = "security-bearing",
) -> None:
    """§7d / §7e: every selected clause (security-bearing, or confirm-look) equals its pinned entry,
    in order; a clause that is new, changed, moved or duplicated, and a pinned clause that is gone,
    each FAIL ``code`` (``sec-pin`` against SEC_PIN_TXT, ``confirm-look`` against
    CONFIRM_LOOK_PINS)."""
    pinned = pin_rows(table or SEC_PIN_TXT)
    count = code.replace("-", "_").replace("sec_pin", "sec") + "_pins"
    for name, text in (("spec", spec), ("hand-off", handoff)):
        want = [(s, w, t) for d, s, w, t in pinned if d == name]
        now = bearing_clauses(name, text, select)
        have = [(s, w, t) for s, w, t, _n in now]
        match = SequenceMatcher(None, want, have, autojunk=False)
        for tag, i1, i2, j1, j2 in match.get_opcodes():
            if tag == "equal":
                continue
            pairs = min(i2 - i1, j2 - j1) if tag == "replace" else 0
            for (s, w, t, num), (_s, _w, was) in zip(
                now[j1 : j1 + pairs], want[i1 : i1 + pairs], strict=True
            ):
                out.fail(
                    code,
                    f"[{code}] {name} line {num}, {s} · {w}: a pinned {kind} clause "
                    f"changed: {clip(was)!r} is now {clip(t)!r}",
                )
            for s, w, t, num in now[j1 + pairs : j2]:
                out.fail(
                    code,
                    f"[{code}] {name} line {num}, {s} · {w}: a {kind} clause the "
                    f"pin does not hold (new, moved or duplicated): {clip(t)!r}",
                )
            for s, w, t in want[i1 + pairs : i2]:
                out.fail(
                    code,
                    f"[{code}] {name}, {s} · {w}: a pinned {kind} clause is gone "
                    f"(changed, moved or deleted): {clip(t)!r}",
                )
        out.n[f"{count}_{'spec' if name == 'spec' else 'handoff'}"] = len(want)
    out.n[count] = len(pinned)


PIN_CODES = ("sec-pin", "confirm-look")


def confirm_look_gate(spec: str, handoff: str, out: Out) -> None:
    """§7e: the confirm-look clauses against CONFIRM_LOOK_PINS (``confirm-look``)."""
    pin_gate(spec, handoff, out, CONFIRM_LOOK_PINS, CONFIRM_LOOK, "confirm-look", "confirm-look")


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
    pin: bool = True,
) -> Out:
    """Sections 2-9 over one spec text (section 1's FAILs carried in from the base); ``pin`` off
    for the in-memory fixture only, whose text the pinned table does not hold."""
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
    if pin:
        pin_gate(spec, base["handoff"], out)
        confirm_look_gate(spec, base["handoff"], out)
    cite_gate(spec, out)
    misc_gate(spec, sec, base, out)
    bq_gate(sec, out)
    out.n.update(
        {
            "mutations": len(MUTATIONS),
            "k_mutations": len(K_MUTATIONS) + len(HAND_MUTATIONS),
            "pin_mutations": len(PIN_FORMS) * 2 + len(PIN_FIXED) + 2 * (GRID_DRAWS + FUND_DRAWS),
            "confirm_look_mutations": len(LOOK_MUTATIONS),
        }
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
        row(n, f"`{f['name']}`", fixture_class(f), *fixture_frame(n, f))
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


def fixture_class(f: dict[str, Any]) -> str:
    """A fixture frame's class: T2's cite, and on a view-as frame its leg first (K8, r3o)."""
    if not f["t2"]:
        return "status"
    return f"{T2_EXACT} (view-as leg first)" if VIEWAS_NAMED.search(f["name"]) else T2_EXACT


def viewas_class_swapped(spec: str) -> str | None:
    """G7 (r3o): frame 69's class cell names the role leg; its prose and keys keep the view-as."""
    m = re.search(r"^\| 69 +\|[^|]*\|( *T2 per §10\.1 \(view-as leg first\) *)\|", spec, MULTI)
    if not m:
        return None
    cell = " T2 per §10.1 (role leg)".ljust(len(m[1]))
    return spec[: m.start(1)] + cell + spec[m.end(1) :]


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


HEX_32 = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{32}(?![0-9A-Za-z])")


def mask_vendor(line: str) -> str:
    """A vendor-shaped run, and a 32-hex fixture id, cut to its first three characters."""
    line = VENDOR_SHAPE.sub(lambda m: m[0][:3] + "\u2026", line)
    return HEX_32.sub(lambda m: m[0][:3] + "\u2026", line)


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
MASK_CELL = "the masked id `...{last4}` and nothing more"
OWNER_LINE = '"API key {key_id_masked} ·'
FIELD_H = 'as G; label "API secret"'
RIGHTS_6 = '"Trade · Withdrawal OFF ✓ · verified 14:02 UTC"'
RESULT_D = "a row the server fills after a pass, with the check list"
FOOTER_36 = "Footer [Cancel] [Back to paste]"
PROSE_4 = 'One "Verify and save" verifies'
PROSE_8 = "opened by every role on a granted account"
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
    # r3o (the orchestrator's text round 3): view / toggle / visibility, the modal fund right, the
    # uncued line (block D's result row, prose, the hand-off), a deck string cut to "off ✓", and
    # frame 69's class
    (
        "V1",
        "view the full key, §6 Key cell",
        "k2.field",
        sec_sub("6", MASK_CELL, "the masked id `...{last4}`; view the full key"),
    ),
    (
        "V1b",
        "View The Full Key, §8 owner key row",
        "k2.field",
        sec_sub("8", OWNER_LINE, '"API key {key_id_masked} · View The Full Key ·'),
    ),
    (
        "V1c",
        "[VIEW THE FULL KEY], frame 36",
        "k1.masked",
        frame_sub(36, FOOTER_36, f"{FOOTER_36} [VIEW THE FULL KEY]"),
    ),
    (
        "V1d",
        "view the full key, §2.5 CMP-034 row",
        "k2.field",
        sec_sub("2.5", "text only, `...{last4}`", "text only, `...{last4}`, view the full key"),
    ),
    (
        "V2",
        "toggle visibility, §4.1 block H",
        "k2.field",
        sec_sub("4.1", FIELD_H, 'as G with toggle visibility; label "API secret"'),
    ),
    (
        "V2b",
        "Toggle Visibility, §6 Key cell",
        "k2.field",
        sec_sub("6", MASK_CELL, "the masked id `...{last4}`; Toggle Visibility"),
    ),
    (
        "V2c",
        "toggle visibility, §8 owner key row",
        "k2.field",
        sec_sub("8", OWNER_LINE, '"API key {key_id_masked} · toggle visibility ·'),
    ),
    (
        "M1",
        "can withdraw, §6 Rights row",
        "k3.withdraw",
        sec_sub("6", RIGHTS_6, '"Trade · can withdraw · Withdrawal OFF ✓ · verified 14:02 UTC"'),
    ),
    (
        "M1b",
        "Can Withdraw, §8 owner key row",
        "k3.withdraw",
        sec_sub("8", OWNER_LINE, '"API key {key_id_masked} · Can Withdraw ·'),
    ),
    (
        "M1c",
        "CAN TRANSFER, frame 36",
        "k3.withdraw",
        frame_sub(36, FOOTER_36, f"CAN TRANSFER. {FOOTER_36}"),
    ),
    (
        "M1d",
        "may withdraw, §4.4 block D result row",
        "k3.withdraw",
        sec_sub("4.4", RESULT_D, f"{RESULT_D}; the key may withdraw"),
    ),
    (
        "B1",
        "bare 12-hex id, §4.4 block D result row",
        "k1.masked",
        sec_sub("4.4", RESULT_D, f"{RESULT_D} for {HEX_12}"),
    ),
    (
        "B1b",
        "bare 12-character id, §4 prose",
        "k1.masked",
        sec_sub("4", PROSE_4, f"Key {BARE_12}. {PROSE_4}"),
    ),
    (
        "B2",
        "[Show] in §4.4 block D result row",
        "k2.field",
        sec_sub("4.4", RESULT_D, f"{RESULT_D} [Show]"),
    ),
    (
        "B2b",
        "[show] in §8 prose",
        "k2.field",
        sec_sub("8", PROSE_8, PROSE_8.replace("opened", "opened [show]")),
    ),
    (
        "B3",
        "[Copy] in §4.4 block D result row",
        "k2.field",
        sec_sub("4.4", RESULT_D, f"{RESULT_D} [Copy]"),
    ),
    ("B3b", "[copy] in §4 prose", "k2.field", sec_sub("4", PROSE_4, f"[copy]. {PROSE_4}")),
    (
        "D1",
        "deck e27.checks.withdrawal.passed cut to off ✓",
        "k3.off",
        sec_sub("12.1", '"OFF ✓ · verified {hh:mm} UTC"', '"off ✓"'),
    ),
    (
        "D1b",
        "deck e27.checks.withdrawal.passed cut to Off ✓",
        "k3.off",
        sec_sub("12.1", '"OFF ✓ · verified {hh:mm} UTC"', '"Off ✓"'),
    ),
    (
        "D2",
        "§2.1 verified row cut to off ✓",
        "k3.off",
        sec_sub("2.1", '"Withdrawal OFF ✓ · verified {hh:mm} UTC"', '"off ✓"'),
    ),
    ("G7c", "frame 69's class names the role leg", "k8.viewas", viewas_class_swapped),
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
# r4o (the re-check of the default-deny pin): the gated words on either side of their noun - each
# form on the confirm while the summary loads (frame 53 and section 2.4's ``consequenceState``) and
# on an exit (frame 53 and frame 11), one mutation each
GATED_FORMS = (
    "disabled",
    "aria-disabled",
    "dimmed",
    "greyed-out",
    "grayed out",
    "inactive",
    "inert",
    "locked",
    "held",
    "hidden",
    "unavailable",
    "unusable",
    "suppressed",
)
PRE_FORMS = (*GATED_FORMS, "no-effect")
POST_FORMS = (*GATED_FORMS, "with no effect", "visible but inactive")
F53_CONFIRM = "[Cancel] alone: the confirm is not in the DOM"
S24_CONFIRM = "Cancel only — the confirm is not in the DOM"
F11_EXIT = "[Cancel] (initial focus)"


def gated_mutations() -> tuple[tuple[str, str, str, Mutation], ...]:
    out: list[tuple[str, str, str, Mutation]] = []
    for i, w in enumerate(PRE_FORMS, 1):
        out += [
            (
                f"G4a{i}",
                f'"a {w} confirm" on frame 53',
                "k4.loading",
                frame_sub(53, F53_CONFIRM, f"[Cancel] and a {w} confirm until the summary loads"),
            ),
            (
                f"G4b{i}",
                f'"a {w} confirm" in section 2.4',
                "k4.loading",
                first_sub(re.escape(S24_CONFIRM), f"Cancel and a {w} confirm", "2.4"),
            ),
            (
                f"G9a{i}",
                f'"a {w} [Cancel]" on frame 53',
                "k9.exit",
                frame_sub(53, "[Cancel] alone", f"a {w} [Cancel] alone"),
            ),
            (
                f"G9b{i}",
                f'"a {w} [Cancel]" on frame 11',
                "k9.exit",
                frame_sub(11, F11_EXIT, f"a {w} {F11_EXIT}"),
            ),
        ]
    for i, w in enumerate(POST_FORMS, 1):
        out += [
            (
                f"G4c{i}",
                f'"the confirm, {w}," on frame 53',
                "k4.loading",
                frame_sub(
                    53, F53_CONFIRM, f"[Cancel] and the confirm, {w}, until the summary loads"
                ),
            ),
            (
                f"G4d{i}",
                f'"the confirm, {w}," in section 2.4',
                "k4.loading",
                first_sub(re.escape(S24_CONFIRM), f"Cancel and the confirm, {w},", "2.4"),
            ),
            (
                f"G9c{i}",
                f'"[Cancel], {w}," on frame 53',
                "k9.exit",
                frame_sub(53, "[Cancel] alone", f"[Cancel], {w}, alone"),
            ),
            (
                f"G9d{i}",
                f'"[Cancel] ..., {w}" on frame 11',
                "k9.exit",
                frame_sub(11, F11_EXIT, f"{F11_EXIT}, {w}"),
            ),
        ]
    return (
        *out,
        (
            "G4e",
            '"[Cancel] beside a dimmed confirm" on frame 53',
            "k4.loading",
            frame_sub(53, F53_CONFIRM, "[Cancel] beside a dimmed confirm"),
        ),
        (
            "G4f",
            'the subject carried by "it" on frame 53',
            "k4.loading",
            frame_sub(53, F53_CONFIRM, "[Cancel] alone: the confirm renders; it stays dimmed"),
        ),
        (
            "G4g",
            "the subject carried in a parenthesis in section 2.4",
            "k4.loading",
            first_sub(re.escape(S24_CONFIRM), "Cancel and the confirm (it is drawn inert)", "2.4"),
        ),
        (
            "G9e",
            '"Cancel has no effect" on frame 53',
            "k9.exit",
            frame_sub(
                53, "Focus: Cancel throughout.", "Focus: Cancel throughout; Cancel has no effect."
            ),
        ),
        (
            "G9f",
            'the exit carried by "it" on frame 53',
            "k9.exit",
            frame_sub(53, "Focus: Cancel throughout.", "Focus: Cancel throughout; it stays inert."),
        ),
    )


# r4o fix: the re-check's ten forms as a sentence of their own, each in lower, Title and UPPER case -
# the confirm forms on frame 53 (the loading frame, read whole), in section 2.4's ``consequenceState``
# (a row naming the load, read whole) and in section 7's prose paragraph that names the load; the
# exit forms on frame 53, in section 2.4's ``consequenceState`` cell and in
# section 2.4's prose
BARE_CONFIRM = (
    "a disabled confirm",
    "a dimmed confirm",
    "a greyed-out confirm",
    "a grayed out Confirm",
    "the confirm, visible but inactive",
)
BARE_EXIT = (
    "a disabled [Cancel]",
    "an inactive Cancel",
    "an unavailable Esc",
    "Close (locked)",
    "the [Close], hidden",
    "a disabled cancel",
    "a dimmed [Back]",
)
CASES: tuple[tuple[str, Callable[[str], str]], ...] = (
    ("lower", str.lower),
    ("Title", lambda x: x[:1].upper() + x[1:]),
    ("UPPER", str.upper),
)
F53_END = "Focus: Cancel throughout."
S7_PARA = "**Data and producers.** "
S24_PARA = "Documented, not forked"


def bare_mutations() -> tuple[tuple[str, str, str, Mutation], ...]:
    out: list[tuple[str, str, str, Mutation]] = []
    for i, form in enumerate(BARE_CONFIRM, 1):
        for case, fn in CASES:
            sent = fn(form) + "."
            out += [
                (
                    f"G4h{i}{case[0]}",
                    f'"{sent}" ({case}) on frame 53',
                    "k4.loading",
                    frame_sub(53, F53_END, f"{F53_END} {sent}"),
                ),
                (
                    f"G4i{i}{case[0]}",
                    f'"{sent}" ({case}) in section 7\'s prose',
                    "k4.loading",
                    sec_sub("7", S7_PARA, f"{S7_PARA}{sent} "),
                ),
                (
                    f"G4j{i}{case[0]}",
                    f'"{sent}" ({case}) in section 2.4\'s consequenceState',
                    "k4.loading",
                    sec_sub("2.4", S24_CONFIRM, f"{S24_CONFIRM}. {sent}"),
                ),
            ]
    for i, form in enumerate(BARE_EXIT, 1):
        for case, fn in CASES:
            sent = fn(form) + "."
            out += [
                (
                    f"G9g{i}{case[0]}",
                    f'"{sent}" ({case}) on frame 53',
                    "k9.exit",
                    frame_sub(53, F53_END, f"{F53_END} {sent}"),
                ),
                (
                    f"G9h{i}{case[0]}",
                    f'"{sent}" ({case}) in section 2.4\'s consequenceState',
                    "k9.exit",
                    sec_sub("2.4", S24_CONFIRM, f"{S24_CONFIRM}. {sent}"),
                ),
                (
                    f"G9i{i}{case[0]}",
                    f'"{sent}" ({case}) in section 2.4\'s prose',
                    "k9.exit",
                    sec_sub("2.4", S24_PARA, f"{sent} {S24_PARA}"),
                ),
            ]
    return tuple(out)


K_MUTATIONS = (*K_MUTATIONS, *gated_mutations(), *bare_mutations())


HAND_ROW = "the egress IP as the key screens' only copy"
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
    # r3o: the hand-off's CMP-033 row (a table row that names no key in its first cell)
    (
        "H4",
        "hand-off row: a bare 32-hex id",
        "k1.masked",
        HAND_ROW,
        f"{HAND_ROW}, beside {HEX_40[:32]}",
    ),
    ("H5", "hand-off row: Can Withdraw", "k3.withdraw", HAND_ROW, f"{HAND_ROW}; Can Withdraw"),
    (
        "H6",
        "hand-off row: view the full key",
        "k2.field",
        HAND_ROW,
        f"{HAND_ROW}; view the full key",
    ),
)


def k_verdict(new: list[tuple[str, str]], code: str) -> tuple[bool, str]:
    """A K mutation's own gate: exactly one FAIL besides the pins, of its own code; the pins'
    ``sec-pin`` and ``confirm-look`` FAILs beside it (the edit touched pinned text, or drew a
    confirm look) are counted, not printed."""
    own = [(c, m) for c, m in new if c not in PIN_CODES]
    pins = len(new) - len(own)
    hit = len(own) == 1 and own[0][0] == code
    got = "; ".join(f"{c}: {m}" for c, m in own) or "none"
    return hit, got + (f" (and the pins: {pins} sec-pin / confirm-look)" if pins else "")


def k_selftest(spec: str, base: dict[str, Any]) -> tuple[bool, list[str]]:
    """Every K mutation on the spec on disk: rc 1 with exactly one distinct FAIL of its own code
    among the specific gates (the default-deny pin refuses it too where it edits pinned text)."""
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
        hit, got = k_verdict(new, code)
        ok = ok and hit
        lines.append(f"{k} {name}: rc {1 if new else 0}, {'ok' if hit else 'WRONG'} — {got}")
    for k, name, code, old, repl in HAND_MUTATIONS:
        if old not in base["handoff"]:
            ok = False
            lines.append(f"{k} {name}: n/a (the hand-off lacks its target)")
            continue
        edited = {**base, "handoff": base["handoff"].replace(old, repl, 1)}
        new = sorted(set(gates(spec, edited).fails) - set(before.fails))
        hit, got = k_verdict(new, code)
        ok = ok and hit
        lines.append(f"{k} {name}: rc {1 if new else 0}, {'ok' if hit else 'WRONG'} — {got}")
    return ok, lines


# r3o: the round-3 lens forms, each once where no security word was (a clause it makes
# security-bearing, so new) and once inside a pinned clause (so changed); the default-deny pin must
# refuse each alone (one distinct FAIL, `sec-pin`)
PIN_FORMS = (
    "see the secret",
    "peek at the key",
    "read out the key",
    "the key in plain text",
    "the key in clear",
    "see the full id",
    "the full key",
    "key visible",
    "the secret is visible",
    "un-mask the key",
    "decrypt the key",
    "download the key",
    "export the key",
    "print the key",
    "email the secret",
    "click to see the key",
    "un-hide the key",
    "withdraw is on",
    "Withdrawal ✓",
    # r3o fix: the fund right and the clear text with no key, secret or withdrawal word
    "can move funds",
    "Can move funds",
    "funds can leave",
    "in clear",
)
# r3o: the view-as prose (the MINOR) and two hand-off placements: (id, name, doc, old, new)
PIN_FIXED: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "P1",
        "§8 prose: the view-as leg first cut",
        "spec",
        "gated in the server's leg order, the view-as leg first (T2 per §10.1;",
        "gated in the server's leg order (T2 per §10.1;",
    ),
    (
        "P2",
        "§10.1 prose: the view-as leg first cut",
        "spec",
        "the view-as leg first on every write — `rbac.view_as`,",
        "on every write — `rbac.view_as`,",
    ),
    (
        "P3",
        "hand-off prose: the key in plain text",
        "hand-off",
        "Fixture values only; no key material",
        "Fixture values only; the key in plain text; no key material",
    ),
    ("P4", "hand-off row: Withdrawal ✓", "hand-off", HAND_ROW, f"{HAND_ROW}; Withdrawal ✓"),
    (
        "P5",
        "hand-off prose: funds can leave",
        "hand-off",
        "Fixture values only; no key material",
        "Fixture values only; funds can leave; no key material",
    ),
    ("P6", "hand-off row: can move funds", "hand-off", HAND_ROW, f"{HAND_ROW}; can move funds"),
    (
        "P7",
        "hand-off prose: in clear",
        "hand-off",
        "Fixture values only; no key material",
        "Fixture values only; shown in clear; no key material",
    ),
    ("P8", "hand-off row: in clear", "hand-off", HAND_ROW, f"{HAND_ROW}; in clear"),
)
# r3o: new phrasings drawn at run time (seeded, so two runs print the same) from a verb x object
# grid, each into a table row and into a prose sentence; every one must FAIL `sec-pin`
GRID_VERBS = ("see", "show", "read", "copy", "export", "print", "send", "decrypt", "unmask", "view")
GRID_OBJECTS = ("the key", "the secret", "the key id")
GRID_DRAWS = 10
GRID_SEED = 816
# r3o fix: a second grid with no key / secret word, so the draws reach the fund right and the
# clear text too: (subject x modal x verb) fund phrasings and (verb x "in clear") placements
FUND_GRID = tuple(
    [
        f"{s} {m} {v}"
        for s in ("funds", "the funds", "money")
        for m in ("can", "may")
        for v in ("leave", "move")
    ]
    + [
        f"{m} {v} {o}"
        for m in ("can", "may")
        for v in ("move", "send", "pull")
        for o in ("funds", "money")
    ]
    + [
        f"{v} {w}"
        for v in ("shown", "stored", "sent", "kept")
        for w in ("in clear", "in the clear")
    ]
)
FUND_DRAWS = 10
# the sections whose tables or prose a specific gate parses strictly (the variants, the deck, the
# reason keys, T2, Appendix A, the BQ rows); a placement there would trip that gate as well
PIN_SKIP = re.compile(r"^(?:0\.|2\.1 |10\.|12\.|14\.|16\.|Appendix A)")


class Draw:
    """A seeded, repeatable draw for the self-test's placements (sha256 of the seed and a counter,
    so two runs pick the same; not a random source for anything else)."""

    def __init__(self, seed: int) -> None:
        self.seed, self.count = seed, 0

    def index(self, n: int) -> int:
        self.count += 1
        return int(sha256(f"{self.seed}:{self.count}")[:12], 16) % n

    def choice(self, items: list[Clause]) -> Clause:
        return items[self.index(len(items))]

    def sample(self, items: list[str], k: int) -> list[str]:
        pool, out = list(items), []
        for _ in range(k):
            out.append(pool.pop(self.index(len(pool))))
        return out


def pin_targets(spec: str, sec: dict[str, str]) -> dict[str, list[Clause]]:
    """The placements a pin mutation may edit: table cells (not a frame row, not a header) and
    prose sentences whose last two words occur once in the spec, outside PIN_SKIP's sections and
    away from an OFF; each split into plain (no security word) and pinned (security-bearing)."""
    frames = {r["raw"].strip() for r in frame_rows(sec).values()}
    lines = spec.split("\n")
    out: dict[str, list[Clause]] = {"row": [], "row+": [], "prose": [], "prose+": []}
    for clause in text_clauses("spec", spec):
        section, where, text, num = clause
        row = where.startswith("row ")
        if PIN_SKIP.match(section) or len(text.split()) < 4 or CONFIRM_LOOK.search(text):
            continue  # a confirm-look clause edited would trip §7e's pin as well
        if OFF_DRAWN.search(lines[num - 1] if row else text):
            continue  # a withdrawal word placed here would tie its OFF (k3.off) as well
        if row and lines[num - 1].strip() not in frames:
            kind = "row"
        elif where == "prose" and spec.count(" ".join(text.split()[-2:])) == 1:
            kind = "prose"
        else:
            continue
        out[kind + ("+" if BEARING.search(text) else "")].append(clause)
    return out


def place(spec: str, clause: Clause, phrase: str) -> str:
    """``phrase`` put inside one clause: a cell gets it appended; a sentence gets it before its
    closing mark (found by its last two words, which occur once)."""
    _section, where, text, num = clause
    if where.startswith("row "):
        lines = spec.split("\n")
        row = cells(lines[num - 1])
        i = next(i for i, c in enumerate(row) if one_space(c) == text)
        row[i] = f"{row[i]}; {phrase}"
        lines[num - 1] = "| " + " | ".join(c.replace("|", "\\|") for c in row) + " |"
        return "\n".join(lines)
    tail = " ".join(text.split()[-2:])
    end = tail[-1] if tail[-1] in ".!?" else ""
    return spec.replace(tail, f"{tail[: len(tail) - len(end)]}, {phrase}{end}", 1)


def pin_selftest(spec: str, base: dict[str, Any]) -> tuple[bool, list[str]]:
    """The default-deny pin's own mutations: each lens form twice, the fixed eight, the grids."""
    before = gates(spec, base)
    if before.fails:
        return False, [
            f"pin list: the spec on disk has {len(before.fails)} FAIL; nothing to mutate"
        ]
    targets = pin_targets(spec, sections(spec))
    rng = Draw(GRID_SEED)
    ok, lines = True, []

    def run(label: str, edited_spec: str, handoff: str, alone: bool) -> None:
        nonlocal ok
        edited = base if handoff == base["handoff"] else {**base, "handoff": handoff}
        new = sorted(set(gates(edited_spec, edited).fails) - set(before.fails))
        codes = sorted({c for c, _m in new})
        hit = codes == ["sec-pin"] if alone else "sec-pin" in codes
        ok = ok and hit
        first = next((m for c, m in new if c == "sec-pin"), "none")
        lines.append(
            f"{label}: rc {1 if new else 0}, {'ok' if hit else 'WRONG'} — {', '.join(codes)} "
            f"({len(new)} FAIL) — {first}"
        )

    for i, form in enumerate(PIN_FORMS, 1):
        plain, pinned = ("row", "prose+") if i % 2 else ("prose", "row+")
        for kind in (plain, pinned):
            clause = rng.choice(targets[kind])
            where = f"{clause[0]} · {clause[1]}"
            run(
                f"R{i}{kind[0]}{'+' if '+' in kind else ''} {form!r} in {where}",
                place(spec, clause, form),
                base["handoff"],
                True,
            )
    for k, name, doc, old, new_text in PIN_FIXED:
        text = spec if doc == "spec" else base["handoff"]
        if text.count(old) != 1:
            ok = False
            lines.append(f"{k} {name}: n/a (its target is not there exactly once)")
            continue
        edited_text = text.replace(old, new_text, 1)
        if doc == "spec":
            run(f"{k} {name}", edited_text, base["handoff"], True)
        else:
            run(f"{k} {name}", spec, edited_text, True)
    grid = [f"{v} {o}" for v in GRID_VERBS for o in GRID_OBJECTS]
    drawn = rng.sample(grid, GRID_DRAWS) + rng.sample(list(FUND_GRID), FUND_DRAWS)
    for j, phrase in enumerate(drawn, 1):
        for kind in ("row", "prose"):
            clause = rng.choice(targets[kind] + targets[kind + "+"])
            run(
                f"G{j}{kind[0]} {phrase!r} in {clause[0]} · {clause[1]}",
                place(spec, clause, phrase),
                base["handoff"],
                False,
            )
    return ok, lines


# r12: §7e's own mutations - the five confirm forms as a sentence of their own, in lower, Title and
# UPPER case, in two prose paragraphs that do not name the load (so ``k4.loading`` stays quiet and
# only the pin refuses them), and a pinned confirm-look paragraph moved to another section and
# duplicated in place
S24_LOOK = "Documented, not forked"
S7_LOOK = "**Keyboard and focus (every dialog).** "
LOOK_PARA = "**E30-D02's dimmed validity look**"


def paragraph(spec: str, start: str) -> tuple[int, int] | None:
    """The paragraph (up to its blank line) whose first line starts with ``start``, once."""
    at = spec.find("\n" + start)
    if at < 0 or spec.count("\n" + start) != 1:
        return None
    end = spec.find("\n\n", at + 1)
    return (at + 1, end + 1) if end > 0 else None


def look_moved(spec: str) -> str | None:
    """Section 9's pinned confirm-look paragraph cut and put before section 7's keyboard one."""
    span = paragraph(spec, LOOK_PARA)
    if span is None or spec.count("\n" + S7_LOOK) != 1:
        return None
    para = spec[span[0] : span[1]]
    cut = spec[: span[0]] + spec[span[1] + 1 :]
    return cut.replace("\n" + S7_LOOK, "\n" + para + "\n" + S7_LOOK, 1)


def look_duplicated(spec: str) -> str | None:
    """Section 9's pinned confirm-look paragraph written twice, the copy right after it."""
    span = paragraph(spec, LOOK_PARA)
    if span is None:
        return None
    para = spec[span[0] : span[1]]
    return spec[: span[1]] + "\n" + para + spec[span[1] :]


def look_mutations() -> tuple[tuple[str, str, Mutation], ...]:
    out: list[tuple[str, str, Mutation]] = []
    for i, form in enumerate(BARE_CONFIRM, 1):
        for case, fn in CASES:
            sent = fn(form) + "."
            out += [
                (
                    f"L{i}a{case[0]}",
                    f'"{sent}" ({case}) in section 2.4\'s "{S24_LOOK}" paragraph',
                    sec_sub("2.4", S24_LOOK, f"{sent} {S24_LOOK}"),
                ),
                (
                    f"L{i}b{case[0]}",
                    f'"{sent}" ({case}) in section 7\'s keyboard paragraph',
                    sec_sub("7", S7_LOOK, f"{S7_LOOK}{sent} "),
                ),
            ]
    return (
        *out,
        ("LM", "a pinned confirm-look paragraph moved (section 9 to section 7)", look_moved),
        ("LD", "a pinned confirm-look paragraph duplicated (section 9)", look_duplicated),
    )


LOOK_MUTATIONS = look_mutations()


def look_selftest(spec: str, base: dict[str, Any]) -> tuple[bool, list[str]]:
    """§7e's mutations on the spec on disk: rc 1 with exactly one distinct FAIL besides the
    security pin, ``confirm-look`` (``sec-pin`` beside it where the edit moves security text)."""
    before = gates(spec, base)
    if before.fails:
        return False, [
            f"look list: the spec on disk has {len(before.fails)} FAIL; nothing to mutate"
        ]
    ok, lines = True, []
    for k, name, fn in LOOK_MUTATIONS:
        mutated = fn(spec)
        if not mutated or mutated == spec:
            ok = False
            lines.append(f"{k} {name}: n/a (the spec lacks its target)")
            continue
        new = sorted(set(gates(mutated, base).fails) - set(before.fails))
        codes = sorted({c for c, _m in new} - {"sec-pin"})
        hit = codes == ["confirm-look"]
        ok = ok and hit
        first = next((m for c, m in new if c == "confirm-look"), "none")
        lines.append(
            f"{k} {name}: rc {1 if new else 0}, {'ok' if hit else 'WRONG'} — "
            f"{', '.join(sorted({c for c, _m in new})) or 'none'} ({len(new)} FAIL) — {first}"
        )
    return ok, lines


def run_mutation(fn: Callable[..., str | None], spec: str, base: dict[str, Any]) -> str | None:
    return fn(spec, base) if fn in (line_drop, t2_uncited) else fn(spec)


def refused(got: Out, before: Out, kind: str, code: str) -> bool:
    """A FAIL mutation raises its code; a WARN mutation raises its WARN and no FAIL but the pin's
    (§7d refuses a moved cite inside pinned text as well, which on the spec is the point)."""
    new_fails = {c for c, _m in set(got.fails) - set(before.fails)} - set(PIN_CODES)
    new_warns = {c for c, _m in set(got.warns) - set(before.warns)}
    return code in new_fails if kind == "FAIL" else code in new_warns and not new_fails


def selftest(base: dict[str, Any], spec: str) -> tuple[bool, list[str]]:
    """The fixture passes and refuses every mutation; a clean spec on disk refuses its share."""
    lines, fx = [], fixture(base)
    before = gates(fx, base, check_markers=True, pin=False)
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
            got_fx = gates(mutated, base, check_markers=True, pin=False)
            hit = refused(got_fx, before, kind, code)
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
    p_ok, p_lines = pin_selftest(spec, base)
    lines += p_lines
    l_ok, l_lines = look_selftest(spec, base)
    lines += l_lines
    restored = gates(spec, base, check_markers=True)
    same = read(SPEC) == spec
    lines.append(
        f"restore: rc {1 if restored.fails else 0}, the spec on disk "
        f"{'byte-identical' if same else 'CHANGED'} (sha256 {sha256(spec)[:12]})"
    )
    ok = ok and k_ok and p_ok and l_ok and same and not restored.fails
    where = (
        "the fixture and the spec on disk" if clean else "the fixture (the spec on disk has FAILs)"
    )
    lines.append(
        f"--self-test: {'ok' if ok else 'FAIL'} — {len(MUTATIONS)} mutations in memory, on "
        f"{where}; "
        f"{len(K_MUTATIONS)} K mutations on the spec and {len(HAND_MUTATIONS)} on the hand-off, "
        "each one FAIL of its own; "
        f"{len(PIN_FORMS) * 2 + len(PIN_FIXED)} pin mutations, each one distinct FAIL (sec-pin), "
        f"and {2 * (GRID_DRAWS + FUND_DRAWS)} drawn phrasings, each refused by the pin; "
        f"{len(LOOK_MUTATIONS)} confirm-look mutations, each one distinct FAIL (confirm-look)"
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
    ("7d. The security text pinned default-deny (sec-pin)", ("sec-pin",)),
    ("7e. The confirm-look clauses pinned default-deny (confirm-look)", ("confirm-look",)),
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
    if "--repin-security" in argv:
        print(render_pins(spec, base["handoff"]))
        return 0
    if "--repin-confirm-look" in argv:
        print(render_pins(spec, base["handoff"], CONFIRM_LOOK))
        return 0
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


# --- the pinned security text (§7d): ``--repin-security`` prints it; a reviewer reads it here ----
SEC_PIN_TXT = r"""
§ spec ‖ E27-D03 — Accounts and key vault hi-fi and desig
@ heading
  # E27-D03 — Accounts and key vault hi-fi and design-system contributions: SCR-125..129, SCR-079,
  SCR-016 step 3 and SCR-019
@ prose
  BQ-1…BQ-16 are **RULED** (main-orchestrator, 2026-10-24 14:22Z, [LANE-hcl49]): all sixteen
  defaults, with BQ-8 bound now by C-2.7 and C-12.2, BQ-14 amended and BQ-11's props consumed by
  name; the riders of BQ-5 and BQ-6 and the supersession of E05-D02's time-limited reveal stay the
  owner's, PROPOSED.
@ prose
  **Revision:** r11 — r10's re-check folded (§16 items 10 and 11): a frame row, a §2.4 row and a
  prose paragraph that name the load are read whole for the confirm, each sentence up to where it
  moves past the load; the exit check reads a bare Esc and Cancel in any case, and also reads
  §2.4's cells and the spec's prose; r10 — the default-deny pin's re-check folded (§16 items 10,
  11 and 13): `k4.loading` and `k9.exit` read the gated words (disabled, dimmed, greyed or grayed
  out, inactive, inert, locked, held, hidden, unavailable, unusable, suppressed, no effect) on
  either side of the confirm or the exit, the appositive ", visible but inactive" included, and a
  token, a password, a balance and "shown in full" make a clause security-bearing; r9 — the
  orchestrator's text round 3 folded as a default-deny pin (§16 item 13): every clause of this
  spec and the hand-off that names a key, a secret, a credential, a fund or money word, a reveal
  or mask word, plain or clear text or CMP-034, CMP-175 or CMP-201, and every statement of the
  view-as leg, equals one entry of the audit tool's pinned table, so security text that is new,
  changed, moved or duplicated fails `sec-pin` until a reviewer reads it there; the word list
  decides which clauses are pinned, and the table what a pinned clause may say; r8 — the
  orchestrator's text round 3 folded into the audit tool (§16 items 10–12): every line is read for
  a bare id, a show, view, copy or toggle of a key or a secret, a visibility toggle, a bracketed
  control that is not the egress IP's copy and a fund right in the modal form ("can withdraw"),
  with no key named on the line; a table row's withdrawal word ties an OFF in any of its cells to
  its time; a view-as frame's class says "view-as leg first"; r7 — the orchestrator's text round 2
  folded into the audit tool (§16 item 12): K1, K2, K3, the dated OFF and the reveal words read
  every clause of every line of this spec and the hand-off, case-insensitive, with no section
  list, and a hit passes only inside a pinned, counted allow-list of exact phrases; a gated frame
  that E27-D02's inventory or its class names as a view-as frame leads with `rbac.view_as`; r5 —
  the orchestrator's text round 1 folded into the audit tool (§16): K1–K3 read every clause of
  every frame row and the secret-field rows outside the frames (§2.3, §4.1, §5) for a bare id and
  a show, copy or toggle control, a withdrawal control, and a withdrawal "OFF" without its time;
  no `lock` on a frame that is not gated; a view-as row of §10.2 leads with its view-as leg; the
  confirm never drawn while the summary loads; an exit gated after a comma; E42-D03's boards PR
  never pinned or quoted; the environment gate reads every frame that names one; and the check
  list's fresh-pass "OFF ✓" dated (D03-C15); r4 — re-pinned at its PR base `e8bca4bb7` (every
  moved `file:line` re-mapped and re-read), and Appendix A's CMP-028 and CMP-044 rows re-based on
  #4414's rewrite of those entries (D03-C16; CMP-015's skeleton token, D03-C12, resolved
  upstream); r3 — the audit tool's gates read each frame row (the standing rule A2's K1–K15, §16),
  each with its own `--self-test` mutation, and the rows that named an element only by reference
  now carry it (§16); r2 — the security and design lens round 1 folded: every withdrawal "OFF"
  dated (D03-C15), the drawer's critical state a badge, the check list's warnings on the triangle
  (HD17), the Enable… dialog, the held step-up request's unanswered re-send, the link on the
  drawer measured, and the audit tool's mirror mutation and OFF gate; r1 — the full text on r0's
  skeleton and audit tool: §1–§17, Appendix A's copy-ready A-rows and the handoff file
  `docs/design/E27/E27-D03-handoff.md`; the boards and their exports follow in the boards PR.
@ prose
  **Scope (the ticket):** hi-fi for every state of E27-D02's inventory (§0, §2–§8), in dark and
  light, with the densities specified (BQ-3, BQ-4); the contributions CMP-175 KeyPermissionBadge,
  CMP-176 AccountKeyRow and CMP-034 MaskedValue, and the documented extensions of CMP-028,
  CMP-035, CMP-044, CMP-066 and CMP-178 (§2); the final copy deck (§12); the Storybook story lists
  (§13).
@ prose
  **Key.** Every `path:line` is at `main` `e8bca4bb7`.
@ prose
  `D02` = `docs/design/E27/E27-D02.md` · `MEMO` = `docs/design/research/e27-key-custody.md`
  (E27-D01) · `PROT` = `docs/design/research/e27-d01-session-protocol.md` · `NN` =
  `docs/plan/NN-*.md` (`05`, `11`, `14`, `15`, `16`, `22` = `22-api-openapi.yaml`, `23`, `24`,
  `31`) · `E05F` = `docs/design/E05/E05-D02-form-controls.md` · `GATE` =
  `.claude/rules/32-design-specs.md` · `TM` = `docs/security/threat-models/E27-accounts.md` · `RB`
  = `docs/ops/runbooks/key-selfcheck.md` · `ADR9` =
  `docs/plan/27-adrs/ADR-0009-secrets-and-key-management.md` · `CON` = `CONSTITUTION.md` · `SECR`
  = `.claude/rules/50-security.md` · `D09` = `docs/design/E09/E09-D09.md` · `D06` =
  `docs/design/E09/E09-D06.md` · `E09D02`, `E30D02` and `E42D02` = those specs under
  `docs/design/` · `E42D01` = `docs/design/research/e42-admin.md` · under
  `services/api/candleviewer/`: `ACT` = `audit/actions.py`, `SU` = `api/step_up.py`, `ASU` =
  `auth/step_up.py`, `SYS` = `net/system_topic.py`, `REV` = `ws/revocation.py` · `MX` =
  `services/api/tests/contract/rbac/matrix.yaml` · `E27.json` and `E43.json` =
  `docs/plan/backlog/E27.json` and `E43.json` (`E43.json:97` is E43-D02's ticket) · another spec
  by its key (`E42-D03` = `docs/design/E42/E42-D03.md`).
@ prose
  Fixture values only (`D02:26-31`): LIVE `Main` (UID 1234567), `sub_001` (1234568) and `sub_002`
  (1234569); DEMO `demo-1` (9000001); users `alex` and `bea`; key ids `...a1b2`, `...c3d4`,
  `...e5f6`, `...a7b8` and `...d9e0`; the documentation addresses `203.0.113.10` and
  `198.51.100.7`.
@ prose
  No real UID, key, secret or IP appears anywhere.
§ spec ‖ Inputs pinned (base `e8bca4bb7`, 2026-10-25)
@ row E27-D02 (`D02`) ‖ State at the base
  merged text-first (#4338, `bf130fe52`), 1245 lines: the 78-frame inventory (`D02:911` "## 7.
  State inventory (AC1, AC5)"), D1–D22 (`D02:185-208`), the T2 rule and the ten PROPOSED E27 state
  keys (`D02:293-322`), the copy deck (`D02:1094-1118`), the component map (`D02:1120-1131`); its
  boards PENDING and not a prerequisite (BQ-1); the owner's `approved` on #733 pending
@ row `15` ‖ State at the base
  the twelve entries Appendix A edits: CMP-011 (`15:149`), CMP-028 (`15:311`), CMP-033 (`15:361`),
  CMP-034 (`15:371` "### CMP-034 MaskedValue"), CMP-035 (`15:381`), CMP-044 (`15:473`), CMP-066
  (`15:681`), CMP-175 (`15:2042`), CMP-176 (`15:2051`), CMP-178 (`15:2068`), CMP-201 (`15:2411`),
  CMP-203 (`15:2429`); #4414 (`04a8caa95`, E05-D02 slice 4) rewrote CMP-015, CMP-028, CMP-043 and
  CMP-044 after E27-D02's base, and Appendix A is re-based on its text (D03-C12, D03-C16)
@ row `16`, `05`, `11` ‖ State at the base
  two density modes (`16:109-114`, `16:138`), three theme presets (`16:137`), bold reserved for
  critical states (`16:85`), the §11.4 handoff checklist (`16:483-489`); text resize (`05:131`);
  no reveal (`11:344` "no reveal control anywhere in the app or API")
@ row `packages/ui/tokens` ‖ Input
  `packages/ui/tokens`
@ row E42-D02, E09-D09, E30-D02, E05-D02 ‖ State at the base
  merged: E42-D02 (#3926, `e0bf7db3e`; DS-1…DS-6 at `E42-D02:1002-1007`), E09-D09 (`baccf724a`;
  the seven `rbac.*` keys), E30-D02 (`f798a64e6`; the validity look, and the refusal string at
  `E30-D02:437`), E05-D02's form controls (`3a2fc5c29`; CMP-034's reveal rules S1–S7 at
  `E05F:748-795`)
@ row E42-D05 ‖ State at the base
  merged text (`docs/design/E42/E42-D05.md`); its Appendix A, applied in a later commit, proposes
  CMP-066's `status` set (`todo`, `current`, `done`, `blocked`, `error`) and stepper tokens
  (`E42-D05:921-922`), not landed: §2.4 consumes them by name, PROPOSED, contract pending, and
  re-reads them before every commit (GATE R6)
§ spec ‖ Acceptance-criteria trace (#816)
@ row AC1 hi-fi covers both themes and all den ‖ Where
  §0 (ten boards, two light twins); a hi-fi row for each of E27-D02's 78 frames with its light
  binding by token (§2.6, §3–§8); high contrast by the computed matrix (§9); the density sheet
  (BQ-4, HD12; "cosy" D03-C1)
@ row AC2 key states survive greyscale and col ‖ Item
  AC2 key states survive greyscale and colour-vision deficiency
@ row AC3 withdrawal-detected reads as blockin ‖ Item
  AC3 withdrawal-detected reads as blocking
@ row AC4 MaskedValue has no reveal ‖ Item
  AC4 MaskedValue has no reveal
@ row AC4 MaskedValue has no reveal ‖ Where
  §2.3, Appendix A (CMP-034), BQ-8 (RULED: binds now, C-2.7, C-12.2); E05-D02's supersession
  D03-C4 and D03-A3
@ row Technical notes — tokens only; the statu ‖ Item
  Technical notes — tokens only; the status scale extended through the DS, never locally;
  SCR-128's compact table legible at 125 %; every string keyed
@ row Test plan — every pair measured; greysca ‖ Item
  Test plan — every pair measured; greyscale and CVD per CMP-175 variant; each `14` checklist
  ticked; copy re-tested
@ row Security notes — misrepresentation is th ‖ Item
  Security notes — misrepresentation is the threat; the Security engineer signs off CMP-175's
  variant set and the SCR-126, SCR-127 and SCR-128 copy; no real UID, key or IP
@ row Accessibility notes — text plus shape; f ‖ Item
  Accessibility notes — text plus shape; focus at 3:1 against both adjacent colours; targets; the
  masked value's description; live regions; 125 % and 200 %
@ row DoD — DS contributions merged with token ‖ Item
  DoD — DS contributions merged with token bindings; zero one-off components
@ row [x] ‖ Item
  SCR-125 (`14:2510`) withdrawal-permission failure is impossible to miss
@ row [x] ‖ Frame (board)
  frame 13 (04 · light 05): the CMP-175 critical badge — "BLOCKED — fund right found", bold, the 2
  px border and the octagon — in the danger treatment, [Start the compromise response] first,
  CMP-092's blocking row, assertive once, over the verdict's failed form, beside the page's
  ordinary warnings — sub_001 degraded and demo-1's Bybit expiry, each on the triangle (§2.1,
  §2.2, §3.4); frame 2 (01 · light 02)
@ row [x] ‖ Item
  SCR-125 (`14:2510`) key-age policy surfaced
@ row [x] ‖ Item
  SCR-125 (`14:2514`) columns (label, UID, environment, permissions, IP allowlist, key age, state)
  drawn
@ row [x] ‖ Frame (board)
  frame 6 (04 · 05): the two-line record of §3.2 — label, UID and pill; the state; the key with
  its rights and withdrawal facets (CMP-175); the allowlist facet; key age · rotation due; health
@ row [x] ‖ Item
  SCR-125 (`14:2514`) the warning state for a missing IP allowlist or a key older than the policy
  is text plus icon
@ row [x] ‖ Frame (board)
  text plus icon throughout; the contract overrides the first half: a missing allowlist is a
  refusal in every environment (`22:2722-2726`; AD-4), so "IP allowlist: none set" takes the
  octagon and the failed class, never a warning — frame 14 (04 · 05); a key older than the policy
  is the warning chip "Rotation due in {n} d" (triangle) or "Rotation overdue" (clock) — frames 9,
  43
@ row [x] ‖ Item
  SCR-125 (`14:2514`) withdrawal-permission-detected state is drawn as a blocking error, not a
  warning
@ row [x] ‖ Item
  SCR-125 (`14:2514`) per-row actions (edit, rotate key, disable, delete) with step-up
@ row [x] ‖ Frame (board)
  frame 11 (04 · 05): the row menu, each ask line before the press — the `keys` class served,
  disable and delete stamped "not yet served — G-8, #895 / #898"; the step-up is SCR-006 on the
  press (T1)
@ row [x] ‖ Item
  SCR-125 (`14:2514`) no secret is ever rendered in the list
@ row [x] ‖ Frame (board)
  CMP-034's `...{last4}` only (§2.3); §12's deck; the tool's scans (§16)
@ row [x] ‖ Item
  SCR-126 (`14:2542`) label, environment, API key and secret fields drawn, with the secret
  write-only (never re-displayed after save)
@ row [x] ‖ Frame (board)
  frames 18, 19, 21 (06): CMP-201's write-only variant, both wells cleared after the save, "Its
  secret can't be shown again."
@ row [x] ‖ Item
  SCR-126 (`14:2542`) the mandatory checks drawn: withdrawal permission must be OFF, IP allowlist
  must be configured, trade+read only
@ row [x] ‖ Frame (board)
  frames 19 and 3 (06; 03): the instruction list and the check list as the contract has them — no
  withdrawal or transfer right, the allowlist exactly the egress IP, only Contract trade — Order
  and Position (`22:2704-2726`); a read-only key is refused (`key_missing_scopes`, `22:2715-2718`)
@ row [x] ‖ Item
  SCR-126 (`14:2542`) edit mode where the secret field is empty and optional
@ row [x] ‖ Frame (board)
  the contract overrides it (D02's C-2; the memo's C17): edit has no key field — the key row with
  Rotate, frame 31 (06)
@ row [x] ‖ Frame (board)
  stated as the contract does it (D02's C-3): "Open orders stay open. Both keys work for 15
  minutes while requests drain." (frame 34) and stage 4's line (frame 38) (07)
@ row [x] ‖ Item
  SCR-127 (`14:2555`) rollback state if the new key fails validation
@ row [x] ‖ Frame (board)
  the contract overrides it: no rollback exists until #897 serves one (G-4); the refused new key
  reads "Nothing changed — the old key ...e5f6 is still active." — frame 36 (07); frame 40
  annotates the absence
@ row [x] ‖ Item
  SCR-127 (`14:2555`) the reminder to delete the old key at Bybit, with a confirmation checkbox
@ row [x] ‖ Item
  SCR-127 (`14:2555`) key-age policy restated
@ row [x] ‖ Item
  SCR-128 (`14:2567`) per-key age, permissions, allowlist and rotation-due state drawn
@ row [x] ‖ Frame (board)
  frame 42 (04 · 05): the key table
@ row [x] ‖ Item
  SCR-128 (`14:2567`) the secrets-at-rest policy stated (where keys live, how they are encrypted,
  who can read them)
@ row [x] ‖ Item
  SCR-128 (`14:2567`) 'mark as compromised' emergency action with its immediate effect (key
  disabled, orders halted for that account)
@ row [x] ‖ Frame (board)
  stated as C-12.12 orders it (D02's C-4): the freeze stops new orders at once, the delete at
  Bybit kills the key, the revoke ends it here — frames 46–48 (04 · 05)
@ row [x] ‖ Item
  SCR-128 (`14:2567`) no secret material is rendered anywhere - verified in copy review
@ row [ ] ‖ Item
  SCR-079 (`14:1753`) equity, available balance, used margin, unrealised PnL, leverage, position
  mode and margin mode drawn with units
@ row [x] ‖ Item
  SCR-079 (`14:1753`) no secret is displayed, ever - verified in copy review
@ row [x] ‖ Frame (board)
  CMP-034's `...{last4}` only; §12's deck
@ row [x] ‖ Item
  SCR-016 (`14:439`) key-entry step never echoes the secret after save
@ row [x] ‖ Frame (board)
  frame 73 (06): both wells cleared; CMP-201 write-only
§ spec ‖ The questions (BQ-1…BQ-16) and the defaults buil
@ prose
  Drafted read-only at the base and ruled by main-orchestrator on 2026-10-24 at 14:22Z
  ([LANE-hcl49]): every default below is built as ruled — BQ-8 bound now, BQ-14 amended, BQ-11's
  props consumed by name — and the riders of BQ-5 and BQ-6 and BQ-8's supersession of E05-D02's
  reveal stay the owner's, PROPOSED, drawn at their defaults meanwhile.
@ row BQ-2 ‖ Default built
  ten composite boards with nested frames, two of them light twins (02 of 01, 05 of 04), restated
  in §0 as a PROPOSED deviation citing the 03:11Z ruling; every state not on a board is a text row
  "not drawn — the text is binding; drawn on request" (precedent `E42-D03:152`); page `E27-D03
  Accounts and key vault hi-fi` (36 characters), boards `E27-D03 / NN slug`, exports
  `docs/design/E27/img/E27-D03-NN-<slug>.png` plus greyscale, deuteranopia and protanopia renders
  for boards 01 and 02; PROPOSED stamps and "not yet served — {gap}, {owner}" strips sit on a
  board annotation layer, never product UI and never a story (`D02:57-58`, `D02:326-331`)
@ row BQ-4 ‖ Default built
  a per-screen density sheet: SCR-125..129 comfortable only (`16:114`; `D02:132-135`), SCR-079
  compact, its trading host's default (`16:113`), with one comfortable inset, SCR-016 and SCR-019
  comfortable; the contributed components (CMP-175, CMP-176, CMP-034, CMP-011, CMP-203, CMP-178)
  specified in both modes, which is where the SCR-128 clause is met — the compact key-table row
  checked at 125 % zoom on 1280 × 800 as a component specimen; zoom: 125 % with no column loss on
  the SCR-125 and SCR-128 tables, 200 % by D02's reflow (`D02:1087-1090`), the in-app text scale
  at its 150 % maximum with `min-height` rows (`16:138`); C-rows to the ticket owner: "cosy" is
  not a mode of `16`, and "200 % text scaling" is read as 200 % zoom plus the 150 % text scale
  (`05:131`)
@ row BQ-5 ‖ Question
  CMP-175: ownership and the variant map
@ row BQ-5 ‖ Default built
  amend OQ-12 (`MEMO:528-533`): this spec owns CMP-175's E27 state set and its visual vocabulary,
  and E43-D02 extends it additively (provenance and time on the verdict, drift naming, SCR-128's
  hardening), its names mapping one to one (verified-off = verified, verified-on =
  withdrawal-detected, unverifiable = not checked, stale = check overdue) — one component, never a
  parallel badge; two scopes, `key` (the facets CMP-176 places) and `aggregate` (the dated
  withdrawal verdict line, `D02:222-227`); served enums replace the boolean props (`15:2045`); the
  ticket's eight variants plus "not checked" and "check overdue", each with its served source,
  class, glyph and word (§2.1); the failure states' row forms stamped "not yet served — G-1, #895
  / #896" (`D02:408-410`); OWNER-LEVEL rider: a stored read-only key (`22:16885`) is specified at
  component level only, with a C-row to the owner and E27-S02 (#896)
@ row BQ-6 ‖ Question
  CMP-175: non-colour encodings and the critical mark
@ row BQ-6 ‖ Default built
  colour reinforces and never carries: (1) every state has its own word, and the critical one
  leads with "BLOCKED"; (2) a glyph per severity class — check (passed, OFF), octagon (blocking,
  failed, down, refused), triangle (warning), clock (time-based warning), dash (not checked), lock
  (T2 only), info (a stored read-only key only) — and no warning-class state ever takes the
  octagon; (3) the critical state alone takes a bold word (`font.weight.bold`, which `16:85`
  reserves for critical states), a 2 px `color.status.danger.strong` border and CMP-176's danger
  treatment; fills are the tone's subtle token with `color.text.primary` labels and the glyphs in
  the strong token, never a solid red fill; glyph names from the registry and DS-5's octagon,
  triangle and clock (`E42-D02:1006`); AC3 by heuristic plus an owner-walkthrough item;
  OWNER-LEVEL rider: a distinct critical hue is the owner's (A6, `16:54`) or DS-6's
  (`E42-D02:1007`), re-raised with §9's evidence and never overridden locally
@ row BQ-7 ‖ Default built
  D02's two-line row in a plain table with `th scope="row"` on the label and no grid
  (`D02:346-357`, `D02:435-436`): line 1 label, UID, environment (word and badge), the state chip,
  CMP-034's key id with CMP-175's key facets and [Actions for {label}]; line 2 CMP-175's allowlist
  facet, key age and rotation due, CMP-178's inline health; "Details for {label}" is the row's own
  disclosure; props drop the inline rotate, revoke and profile callbacks (`15:2054`) for a menu
  model whose items carry their T2 second lines, a details slot and a served `state`; the chip is
  CMP-011 with D02's words in D02's precedence (`D02:365-366`, `D02:1099`); blocked is the danger
  treatment (`D02:403-410`): a `color.status.danger.subtle` fill, a 4 px
  `color.status.danger.strong` inline-start rule (a border, so it survives forced colours), the
  bold "BLOCKED — fund right found" chip with the octagon and [Start the compromise response]
  first, never dismissible; disabled has two forms at full text contrast, never
  `color.text.disabled` or `opacity.disabled` (`D02:326-327`) — "Disabled at {hh:mm} UTC — doesn't
  trade here. [Enable…]" (`D02:751`) and "Off by policy", stamped "not yet served — G-12, #3657"
  with no control (`D02:636-638`); one card per account at 200 % (`D02:1087-1088`)
@ row BQ-8 ‖ Question
  CMP-034: permanently masked
@ row BQ-8 ‖ Default built
  no reveal anywhere (AC4; `11:344`; D13 at `D02:199`; AD-11 at `MEMO:407`): CMP-034 renders only
  the server's masked id (`22:16879-16882`) and never receives a full value; its props are the
  masked id and `label`, and the toggle, the timer and the copy affordance are removed; masked is
  its only state; a description in the DOM at mount says the value is write-only and can't be
  shown; the entry records why the variant is absent and annotates "secret reveal" as a historical
  name; secret entry takes a write-only CMP-201 variant (no toggle, autocomplete suppressed,
  cleared on leave, paste allowed; `15:2414`), to which E05-D02's leak rules S4–S7 move; riders:
  CMP-035 drops "secret auto-hide" and CMP-033 drops "API key display"; it settles E05-D02's open
  review G19 / E05-X02 (`E05F:448-453`); RULED to bind now (C-2.7, C-12.2): only the supersession
  of E05-D02's time-limited reveal stays the owner's, as a C-row and a copy-ready A-row to
  E05-D02's owner (D03-C4, D03-A3), and no board draws a reveal meanwhile
@ row BQ-9 ‖ Default built
  the global banner is CMP-092 DegradedModeBanner, consumed, whose blocking row is the one
  announcement for the condition (`15:929-935`); the panel notice is a CMP-028 extension: the
  danger tone in a blocking, non-dismissible form that announces nothing itself, with a stable id
  that every blocked key control's `aria-describedby` points at (one notice, many pointers), the
  octagon and D02's two sentences (`D02:1117`); Revoke stays enabled (D17); an H-row to E43-D02
  (#1139): its CMP-028 severity set keeps this form
@ row BQ-10 ‖ Default built
  SCR-127 stage 4 only; the served `overlap_until` (`22:17130-17134`; the 900 s is fixed,
  `22:2883-2892`) is the primary, absolute time ("until 10:55:01 UTC") and the relative mm:ss is
  secondary, on server-corrected time; the stage advances on the server's `state`, never on the
  timer reaching 0; polite announcements at 60 s, 10 s and the end (D21); no colour change under
  the threshold, bound to `color.text.secondary` (`color.text.warning` is not a token, `15:386`);
  the row shows only the absolute line (`D02:578`), nothing ticking in a list; `Esc` at stage 4
  closes the view while the overlap continues (`D02:586-590`); A-rows replace `font.mono` with
  `type.num.*`, drop `color.text.warning` and drop "secret auto-hide"
@ row BQ-11 ‖ Default built
  consume E42-D03's unlanded rung props (`E42-D03:902-904`) by name, PROPOSED with a "contract
  pending" stamp until they land (the ruling), and add only: the consequence-summary loading
  state, with no confirm rendered, Cancel only, "Reading what sub_002 holds…" and "Still reading…"
  after 1 s (`D02:723-729`); the title's environment suffix (`D02:262-270`); the typed token, the
  account label or the server's `target` (`D02:266-267`); `Enter` in the typed field never
  confirms (D22); the ask line before the press, stamped "not yet served — G-8, #895 / #898" for
  disable and delete; the audit marker last (CMP-093, `E42-D03:691`); two radios, none checked,
  the stop-loss radio gated on `accounts.stop_missing` (D10); validity is E42-D03's model, the
  confirm `aria-disabled` and focusable with its hint in the validity look (D02 only allows native
  `disabled`, `D02:1027-1039`); every A-row reads "if E42-D03's boards PR lands its Appendix A
  first, re-read and re-base" (GATE R6); OQ-9 and OQ-10 stay the owner's (#2701), drawn at their
  PROPOSED defaults
@ row BQ-12 ‖ Default built
  one stepper with a `list` or `nav` form: SCR-127's dialog makes each stage a labelled region
  with `aria-current="step"` and focus to the stage heading (`D02:542`, `D02:586-588`), SCR-126
  and SCR-016 use the `nav` form (`D02:444`, `D02:850`); statuses in glyph and word — done
  (check), current, upcoming, refused at stage 3 (octagon, "Nothing changed") — with no "rolled
  back" or "failed" status and no progress bar (G-4; AD-6); an optional per-step `meta` ("Verify ·
  2.4 s", `D02:570`) from real request or server timestamps, never simulated (D18; AD-16); a
  collapsed form "Stage 2 of 5 — Paste and confirm" at 200 % and on narrow widths (`D02:1089`);
  concrete strong-glyph and `color.text.*` label tokens replace the bare status tokens (`15:686`);
  a rider to E27-D04: checks appear progressively only when real backend progress drives them
@ row BQ-13 ‖ Question
  CMP-178 for per-key health
@ row BQ-13 ‖ Default built
  an inline, text-first form of CMP-178 with no tile chrome, sparkline or heading link: word,
  glyph and heartbeat age — "Healthy · 2 s" (check), "Degraded — REST only" (triangle), "Down —
  order entry off for this account" (octagon) with "last heartbeat {hh:mm:ss} UTC" (`D02:350`,
  `D02:415-417`, `D02:786`); no number for a value not received (E42-D02 D4); no live region of
  its own, transitions going through the shell announcer once (D21; `D02:1078-1079`); built on
  E42-D03's unlanded props (`E42-D03:892-896`), qualified per GATE R6; used in CMP-176's line 2
  and SCR-079's key block; never CMP-210, whose chips link to admin screens
@ row BQ-14 ‖ Default built
  every E27-D02 element on an existing CMP (§2.5): the verdict line is CMP-175 `aggregate`; the
  check list is CMP-203 extended to three outcomes (check, octagon, dash) plus a detail line,
  without its list-wide live region (`D02:235-238`); the row chip is CMP-011; the details row is
  CMP-176's disclosure; the compromise card is a documented composition (CMP-050 as a region, an
  ordered list, CMP-001 and CMP-005); the Bybit-delete note is CMP-005; the allowlist row and the
  drawer's key block are CMP-036, with CMP-033 on the egress IP only; elapsed time is CMP-066's
  `meta`; stamps are board annotations; Appendix A (old text verbatim at the base, then new) for
  CMP-175, 176, 034, 028, 035, 044, 066, 178, 201, 203, 011 and 033 as copy-ready A-rows in this
  text PR, which the catalogue owner applies (amended by the ruling: neither `15` nor `14` is
  edited here), and the boards PR adds only content-only pointer lines, one per SCR block (the
  eight screens) and one per CMP block; A-rows to E09-D09 §3.1 (the ten E27 state keys) and
  E30-D02 §14 (C-9, `D02:1204`); the handoff file `docs/design/E27/E27-D03-handoff.md` written now
  (`16:483-489`), which E27-D06 embeds by reference
@ row BQ-15 ‖ Default built
  keyed ids `e27.{screen}.{element}[.{state}]` beside the `keys.*`, `accounts.*` and `rbac.*`
  reason keys, each row with its Where, String and Status · source (`unchanged` byte-equal to the
  memo seed and gated, `refined` with the change noted, `new` PROPOSED, `consumed` verbatim from a
  merged spec); validation by the adaptation — a heuristic re-test against CP-1…CP-6 and H7 (every
  "delete" and "revoke" says where it happens), a written protocol for two people outside the D01
  sessions and owner-walkthrough items, nothing claimed as measured; H6's predicted misreads
  (CP-2, CP-4, CP-6; `MEMO:194`) are placed better, not rewritten; CD-2's failed clause reuses
  E30-D02's words (`E30-D02:437`); the strings D02 named but never wrote are written; one string
  for both Bybit-delete checkboxes (`MEMO:296`); before any check, CP-3's address and its [Copy]
  are a target state stamped "not yet served" (`22:2745-2749`), a G-row to E27-S02 (#896), never
  an IP echo; the delete warning says "This can't be undone, though the same Bybit account can be
  added again as a new one."
@ row BQ-16 ‖ Default built
  `docs/design/_tools/e27_d03_hifi_audit.py` (this PR): stdlib only, offline, `python3 -I -B` with
  `--check`, `--json` and `--selftest`, importing `verify_tokens.py`, `contrast_check.py`,
  `cvd_simulate.py` and `e27_d02_wires_audit.py`; it gates the matrix with its reproductions and
  CR: rows, the AC2 carriers, token bindings, the inventory and the cap, T2, the copy deck,
  Appendix A (WARN on drift, FAIL if gone or ambiguous, WARN on CMP-044 and CMP-178 while
  E42-D03's boards PR is open), cites, scans, counts and markers, and refuses a mutation set (§16
  lists every check); protanopia: an additive third output of `cvd_sim.py` (Machado 2009) for
  boards 01 and 02, landed with the boards PR, existing callers unchanged
§ spec ‖ 0. The boards (PENDING; ten under the lever-4 ca
@ prose
  Page **`E27-D03 Accounts and key vault hi-fi`** (36 characters), created by name by the board
  script at the boards step and its id recorded then (`docs/design/README.md:46-49`).
@ prose
  **PROPOSED deviation (the lever-4 board cap: main-orchestrator, 2026-10-24 03:11Z,
  [LANE-hcl39]).** The ruling, quoted: "the lever-4 board cap applies to every not-yet-drawn set,
  old specs included: **≤ 10 boards per ticket, light twins ≤ one third**, chosen for the evidence
  that matters (the T2 / safety / contrast / state-matrix boards; one anatomy; one keyboard-a11y;
  the redline of the one contract-bearing screen); every other sheet is listed in §0 as "not drawn
  — the text is binding; drawn on request", which the owner's text-first lever already allows."
  AC1's "every state … in dark and light" is therefore met in text: every one of E27-D02's 78
  frames has a hi-fi row with its light binding by token (§2–§8), ten composite boards draw the
  evidence, two of them light twins of the contrast-critical boards (BQ-2), and high contrast is
  proven by the computed matrix (§9; the E42-D03 Q6 precedent, `E42-D03:152`).
@ prose
  The board choice follows the ruling's order and its tie-breaker (contrast-critical screens, the
  DEMO / LIVE badge, the two disabled looks), and E27-D02's own guidance (main-orchestrator,
  2026-10-24 07:35Z): the key add, rotate and revoke with the step-up, the C-2.8 refusal and the
  Manager and Viewer legs first, then the keyboard board.
@ row 01 ‖ Board
  `E27-D03 / 01 cmp-175-key-states`
@ row 01 ‖ Frames (E27-D02 §7)
  `Pattern / withdrawal verdict: dated, overdue, failed, unavailable, no keys`
@ row 01 ‖ Draws
  every CMP-175 state in its `key` and `aggregate` forms (frame 2 nested); the CMP-011 row chips;
  CMP-034; the greyscale, deuteranopia and protanopia strips of the variant set
@ row 01 ‖ Export (planned)
  `docs/design/E27/img/E27-D03-01-cmp-175-key-states.png`
@ row 02 ‖ Board
  `E27-D03 / 02 cmp-175-key-states-light`
@ row 02 ‖ Export (planned)
  `docs/design/E27/img/E27-D03-02-cmp-175-key-states-light.png`
@ row 03 ‖ Frames (E27-D02 §7)
  `Pattern / check list: passed, failed, not checked`; `Pattern / T2 anatomy with the E27 state
  keys`; `Pattern / rung 1 and rung 3 dialogs as used here`
@ row 03 ‖ Draws
  CMP-176 rows (BQ-7) and their 200 % card; CMP-178 inline; CMP-203 tri-state; CMP-201 write-only;
  the CMP-028 KEK notice; CMP-035; CMP-066; CMP-044 rung 1 and rung 3; the T2 anatomy beside the
  validity look
@ row 04 ‖ Frames (E27-D02 §7)
  `CMP-087 / the accounts route in the admin shell`; `SCR-125 / ok`; `SCR-125 / empty`; `SCR-125 /
  loading and error`; `SCR-125 / key expiring (<14 d): rotation due and Bybit expiry`; `SCR-125 /
  within Bybit's 48 h new-key restriction`; `SCR-125 / row menu and Test`; `SCR-125 / at the
  sub-account cap`; `SCR-125 / withdrawal permission detected: blocking error`; `SCR-125 / IP
  whitelist missing or mismatched`; `SCR-125 / key invalid`; `SCR-125 / health degraded and down`;
  `SCR-125 / KEK unavailable`; `SCR-128 / key table and the secrets-at-rest policy`; `SCR-128 /
  overdue rotation`; `SCR-128 / Test passed while trading is read-only`; `SCR-128 / KEK
  unavailable: one panel notice`; `SCR-128 / mark as compromised: the ordered card`; `SCR-128 /
  compromise card: the revoke refused`; `SCR-128 / compromise card: after the Bybit delete, the
  account reads dead`
@ row 06 ‖ Board
  `E27-D03 / 06 scr-126-add-key`
@ row 06 ‖ Frames (E27-D02 §7)
  `SCR-126 / register the account shell`; `SCR-126 / paste the key: write-only fields and the
  allowlist row`; `SCR-126 / validating state`; `SCR-126 / verified and stored: the result panel`;
  `SCR-126 / validation: format, duplicate UID, the sixth sub-account`; `SCR-126 / refused:
  withdrawal or transfer right`; `SCR-126 / refused: IP allowlist, Bybit refused the egress IP`;
  `SCR-126 / refused: IP allowlist, CandleViewer's rule`; `SCR-126 / refused: the other checks`;
  `SCR-126 / no verdict: nothing stored`; `SCR-126 / activation failed after a pass`; `SCR-126 /
  KEK unavailable`; `SCR-126 / step-up gate before save`; `SCR-126 / edit mode: no key field, the
  key row with Rotate`; `SCR-126 / edit conflict and refusals`; `SCR-016 / step 3 loading:
  verifying`; `SCR-016 / step 3 valid: verified and stored`; `SCR-016 / step 3 invalid: a check
  refused`; `SCR-016 / step 3 skipped: Skip for now`
@ row 06 ‖ Draws
  key add with the step-up; the C-2.8 refusal (CP-5); SCR-016 step 3 as insets
@ row 06 ‖ Criterion (the 03:11Z ru
  safety and T2: the key add with the step-up; the withdrawal refusal
@ row 06 ‖ Export (planned)
  `docs/design/E27/img/E27-D03-06-scr-126-add-key.png`
@ row 07 ‖ Frames (E27-D02 §7)
  `SCR-127 / stage 1: create the new key at Bybit`; `SCR-127 / stage 2: paste and confirm`;
  `SCR-127 / stage 3: verifying, elapsed time per stage`; `SCR-127 / stage 3 refused: nothing
  changed, the old key still active`; `SCR-127 / stage 3 no verdict: nothing changed`; `SCR-127 /
  stage 4: switched, the 900 s overlap`; `SCR-127 / stage 5: old key revoked here, delete it at
  Bybit`; `SCR-127 / not yet served: drain read, rollback, early revoke, failed`; `SCR-127 / KEK
  unavailable: Rotate is T2`
@ row 07 ‖ Draws
  rotate with the step-up; the countdown; the refused new key
@ row 08 ‖ Frames (E27-D02 §7)
  `SCR-129 / revoke a key that is not the last: rung 1`; `SCR-129 / revoke the last key with
  exposure: two choices, none selected`; `SCR-129 / revoke refused: a position without its
  stop-loss`; `SCR-129 / revoked: the outcome and the Bybit line`; `SCR-129 / loading the
  consequence summary`; `SCR-129 / disable: consequences and the typed label`; `SCR-129 / disable
  with exposure: two choices, none selected`; `SCR-129 / exposure unknown: dead or fixable`;
  `SCR-129 / exchange error`; `SCR-129 / delete (keeps history): no exposure`; `SCR-129 / delete
  blocked by open exposure`; `SCR-129 / delete on an account that never had a key: T2`; `SCR-129 /
  disabled and deleted: the outcome lines`
@ row 09 ‖ Frames (E27-D02 §7)
  `SCR-079 / healthy (owner)`; `SCR-079 / key expiring soon`; `SCR-079 / key invalid`; `SCR-079 /
  IP-whitelist mismatch`; `SCR-079 / stale balance`; `SCR-079 / healthy (manager)`; `SCR-079 /
  healthy (viewer)`; `SCR-079 / viewing as a manager`; `SCR-079 / disabled or suspended account`;
  `SCR-079 / no API key yet`
§ spec ‖ 1.1 Locked inputs — cited, never re-decided
@ row E27-D02's binding and consumed decisions ‖ What it fixes here
  D1 the shell (SCR-125..129 inside CMP-087, SCR-079 a trading drawer outside it; consumed) · D5
  one "Verify and save" that verifies and stores (binding: the call) · D6 the allowlist a
  read-only row, the egress IP the only copyable value (binding: the rule) · D8 the contract's
  five rotation stages (binding) · D9 C-12.12's compromise order (binding) · D10 the contract's
  exposure choices, none checked (binding) · D12 the rule's words, never exchange text (binding) ·
  D13 no reveal anywhere (binding) · D19 the ladder (consumed) · D20 "not yet served" for an
  unserved source (consumed) · D22's keys, Cancel first and focus return (consumed)
@ row E30-D02 (consumed) ‖ What it fixes here
  §14's state keys (`frozen`, `lockout`, `arm.locked`, `pending_key`) and the off-by-policy
  refusal
@ row E05-D02 (consumed) ‖ What it fixes here
  CMP-007's field well, `color.surface.app` (G4); CMP-034's leak rules S4–S7, moved to CMP-201's
  write-only variant (§2.3)
§ spec ‖ 1.2 The hi-fi decisions (HD1…HD17)
@ row HD1 ‖ Decision
  CMP-175 holds the E27 state set: thirteen states in two scopes, `key` and `aggregate`, from
  served enums with no default — a missing or unknown state renders "not checked" or nothing,
  never OFF; E43-D02 extends the set additively (§2.1)
@ row HD2 ‖ Decision
  Every state is its own word with its class's glyph; the critical mark — a bold word and a 2 px
  `color.status.danger.strong` border — is withdrawal-detected's alone; fills are the tone's
  subtle token with `color.text.primary` words and the strong token on the glyph; no solid red and
  no local hue (§2.1, §9)
@ row HD3 ‖ Decision
  CMP-176's state slot is one badge, the worst that applies: CMP-175's own word for a
  key-verification state (BLOCKED, Expired at Bybit, the two allowlist states, Check overdue,
  Withdrawal: not checked, Bybit expiry) and a CMP-011 chip for every other state, in E27-D02's
  precedence with four additions (§2.2, §3.2)
@ row HD5 ‖ Decision
  CMP-034 is text only — `...{last4}` in `type.num.base`, no box, no control, no timer — with its
  description in the DOM at mount; secret entry is CMP-201's `writeOnly` variant, to which
  E05-D02's S4–S7 move (§2.3)
@ row HD6 ‖ Decision
  The KEK notice is CMP-028's `blocking` danger form: one per screen, silent (CMP-092's row is the
  one announcement), a 2 px border, the stable id every blocked key control points at; Revoke
  stays enabled (§2.4)
@ row HD8 ‖ Decision
  CMP-044 takes E42-D03's rung props by name; its deltas are the summary before any confirm
  renders, the environment in the title, the typed token and `Enter` never confirming; an unmet
  confirm takes E42-D03's validity form (`color.surface.raised`, a hairline, a
  `color.text.tertiary` label and the hint); the destructive confirm is `color.text.primary` on
  `color.status.danger.subtle` with a 1 px `color.status.danger.strong` border; the DOM runs in
  E42-D03's rung order with focus on Cancel (§2.4, §7, §11)
@ row HD13 ‖ Decision
  Themes: dark boards and two light twins, every state's light binding by token, high contrast by
  the computed matrix, forced colours as a mapping per carrier (§0, §9)
@ row HD14 ‖ Decision
  Before any check this client ran the egress IP and its Copy are a target state stamped "not yet
  served", never an address another service echoes — SCR-125's details row (frame 14) included,
  although the hourly self-check judged the stored key; from a served result the address is live,
  with CMP-033 its only copy control (§3, §4, §5, §6, §8)
@ row HD15 ‖ Decision
  One keyed id per string: every screen row cites §12.1's ids, and the deck wins where a row
  paraphrases; the screens' working keys were folded into the deck's ids at assembly (§12)
@ row HD16 ‖ Decision
  SCR-128's table is a plain table with a visible caption; the Status cell is the `KeyStatus`
  word; the rotation state is CMP-011's chip under the date, never E27-D02's "OK" and "due"; the
  rights and allowlist cells are CMP-175's facets (§6)
§ spec ‖ 2.1 CMP-175 KeyPermissionBadge — the variant set
@ heading
  ### 2.1 CMP-175 KeyPermissionBadge — the variant set (AC2, AC3)
@ prose
  This spec owns CMP-175's E27 state set and its visual vocabulary, which amends OQ-12
  (`MEMO:528-533`); E43-D02 (#1139) extends it additively — Bybit provenance on the verdict, drift
  naming, SCR-128's hardening — and its `VerificationVerdict` names map one to one: `verified-off`
  is `verified`, `verified-on` is `detected`, `unverifiable` is `not_checked` and `stale` is
  `overdue` (`E43.json:97`; D03-H4, §14).
@ prose
  One component, never a parallel badge: every withdrawal, rights and allowlist verdict word in
  E27 is a CMP-175 word, and so is Bybit's own expiry, while the rotation policy's clock stays
  CMP-011's (D7, `D02:193`).
@ prose
  The table is the variant set the audit tool gates (§16): one row per state — the ticket's eight
  (its CMP-175 deliverable), read-only's import and stored forms apart, plus "not checked", "check
  overdue" and the allowlist facet's pass and unread forms.
@ row verified ‖ Facet
  withdrawal
@ row verified ‖ Served source
  the key's latest check passed with `withdraw_enabled: false` (`22:16947-16951`) and its
  `last_verified_at` (`22:16888`) lies inside the freshness window: no
  `accounts.key_verification_stale` or `accounts.key_selfcheck_failed` notice holds
  (`23:4265-4269`); per key from `withdrawal_permission_present: false` once G-1 serves it
  (`22:22028-22030`; O-A)
@ row verified ‖ Word
  "Withdrawal OFF ✓ · verified {hh:mm} UTC" (`D02:349`, dated per AD-3, `MEMO:399`)
@ row read-only (stored; BQ-5 rider, OWNER-LEV ‖ Served source
  `read_only: true` on a stored key (`22:16885`; `key_not_read_only`, `22:2718`); no story, `14`
  state or E27-D02 frame shows one, so it is specified here and on board 01 only, with a C-row to
  the owner and E27-S02 (#896) (D03-C3, §14)
@ row withdrawal-detected (critical) ‖ Variant
  withdrawal-detected (critical)
@ row withdrawal-detected (critical) ‖ Facet
  withdrawal
@ row withdrawal-detected (critical) ‖ Served source
  a stored key's check found a fund right: `withdrawal_permission_present: true`, which "raises a
  critical finding immediately" (`22:22028-22030`); its row form is a target state stamped "not
  yet served — G-1, #895 / #896" (`D02:408-410`); on import the same fact is CP-5's refusal
  (`key_withdraw_permission`, `22:2707-2710`; `D02:1102`), a CMP-027 line, never this badge
@ row withdrawal-detected (critical) ‖ Word
  "BLOCKED — fund right found" (`D02:405`)
@ row expired ‖ Word
  "Expired at Bybit" (new; the check row's "This key has expired at Bybit.", `D02:249`)
@ row not checked ‖ Facet
  withdrawal
@ row not checked ‖ Word
  "Withdrawal: not checked" (D4, `D02:190`; AD-2, `MEMO:398`)
@ row check overdue ‖ Facet
  withdrawal
@ row allowlist matches ‖ Served source
  `ip_whitelist_matches_egress: true` (`22:16960-16964`); per key from
  `ip_whitelist_matches_expected` once G-1 serves it (`22:22031`)
@ prose
  **Reading the table.** The word carries each state and is its own (AC2); the glyph repeats the
  class — check pass, octagon failed and critical, triangle warning, clock time warning, dash not
  checked, info a stored read-only key, and the lock is T2's alone — and no warning-class state
  ever takes the octagon (BQ-6; `D02:235`, `D02:634`).
@ prose
  "OFF" appears in the verified word only and always with its time (AD-3); a key whose rights were
  never read reads "Withdrawal: not checked" (`22:16950`, `22:16988-16990`).
@ prose
  The fills cannot carry it, as §9 measures: under deuteranopia the critical and pass fills sit
  ΔE76 4.46 <!-- audit:cvd.fill-critical-pass.dark.deuteranopia=4.46 --> apart in dark and 1.05
  <!-- audit:cvd.fill-critical-pass.light.deuteranopia=1.05 --> in light, under the 5.0 JND; the
  octagon's and the triangle's strong tokens are one colour in light, ΔE76 0.00 <!--
  audit:cvd.glyph-critical-warning.light.normal=0.0 --> in every simulation (DS-6,
  `E42-D02:1007`); and in greyscale the danger and warning fills are Rec.
@ prose
  **AC3 — withdrawal-detected reads as blocking.** Beside the ordinary warnings — rotation due,
  Bybit expiry and degraded on the triangle, check overdue and rotation overdue on the clock
  (`D02:389-392`, `D02:415`, `D02:634-635`) — the critical state is the octagon; beside the failed
  states, which share the octagon, it alone is a bold word inside a 2 px border, and its word
  leads with "BLOCKED"; bold is reserved for critical states (`16:85`).
@ prose
  Its row adds the danger treatment (§2.2), the page the server's read-only banner and the negated
  verdict (`D02:403-410`), and its first control starts the compromise response, never Rotate
  (OQ-13; `keys.compromise_path`, `D02:316`).
§ spec ‖ CMP-175: scopes, forms and the aggregate line
@ heading
  #### CMP-175: scopes, forms and the aggregate line
@ prose
  - **`key` scope** — one facet of one key: withdrawal, rights, allowlist or expiry.
@ prose
  Two forms: `badge` (fill, glyph and word: CMP-176's state slot, and the critical state
  everywhere) and `inline` (glyph and word on the host's surface: CMP-176's facet cells, SCR-128's
  table cells and SCR-079's key block).
@ prose
  No expiry, or one beyond 14 days, draws no expiry facet; the drawer's key line then states the
  date or "Bybit expiry: none" as plain metadata (`D02:784`).
@ prose
  - **`aggregate` scope** — the withdrawal verdict line under SCR-125's `h1` (D3; `D02:212-230`):
  one line, never dismissible, its words the carrier.
@ row dated ‖ When (served)
  no `accounts.*` read-only notice holds; every stored key passed
@ row dated ‖ Text
  "Withdrawal: OFF on all {n} accounts with a key ✓ · verified {hh:mm} UTC" (`D02:222`)
@ row overdue ‖ Text
  "Withdrawal check overdue — last passed {hh:mm} UTC. Trading is read-only until a restart passes
  the check." (`D02:223`)
@ row unavailable ‖ Text
  "Withdrawal check could not run — trading is read-only until a restart passes the check."
  (`D02:225`)
@ row read failed ‖ Text
  "Withdrawal verdict unavailable — the accounts could not be read." (`D02:225`)
@ row no keys ‖ Form
  no keys
@ row no keys ‖ When (served)
  no account holds a stored key
@ row no keys ‖ Text
  "No stored keys yet — nothing to check." (`D02:226`)
@ row loading ‖ Text
  "Withdrawal verdict loading…" (`D02:387`), never OFF
§ spec ‖ CMP-175: props — served enums
@ heading
  #### CMP-175: props — served enums
@ row `scope` ‖ Type
  `"key" | "aggregate"`
@ row `facet` ‖ Type
  `"withdrawal" | "rights" | "allowlist" | "expiry"`
@ row `facet` ‖ Rule
  `key` scope only
@ row `state` ‖ Type
  withdrawal `"verified" | "detected" | "not_checked" | "overdue"`; rights `"trade" |
  "missing_scopes" | "read_only"`; allowlist `"matches" | "missing" | "mismatch" | "not_checked"`;
  expiry `"expiring" | "expired"`
@ row `state` ‖ Rule
  required, no default: a missing or unknown value renders the facet's "not checked" form
  (withdrawal, allowlist) or nothing (rights, expiry), never a pass
@ row `count`, `asOf` ‖ From
  the accounts with a stored key; the oldest `last_verified_at` (O-B)
@ prose
  They replace `permissions: {trade, read, withdraw}` and `ipWhitelisted: boolean` (`15:2045`):
  two booleans cannot say "not checked" or "overdue", and a defaulted `false` would draw "OFF ✓"
  for a key whose rights were never read, which the contract forbids (`withdraw_enabled` is "sent
  only once the key's rights were read, never as a default", `22:16950`).
§ spec ‖ CMP-175: states × tokens (dark; light and high c
@ heading
  #### CMP-175: states × tokens (dark; light and high contrast bind the same names)
@ row `inline` form ‖ Glyph
  the class's token
@ row `aggregate` line ‖ Glyph
  the class's token
§ spec ‖ CMP-175: sizes per density
@ heading
  #### CMP-175: sizes per density
§ spec ‖ CMP-175: accessibility and keyboard
@ heading
  #### CMP-175: accessibility and keyboard
@ prose
  - No live region of its own: its host announces a transition once through the shell announcer —
  a failed key assertive, a recovery polite (D21; `D02:1078-1079`) — and the aggregate line per
  the forms table.
§ spec ‖ CMP-175: current → gap → proposal
@ heading
  #### CMP-175: current → gap → proposal
@ row CMP-175 KeyPermissionBadge (Atom, securi ‖ CMP
  CMP-175 KeyPermissionBadge (Atom, security-critical)
@ row CMP-175 KeyPermissionBadge (Atom, securi ‖ Current (`15:2042-2049`)
  two booleans, `permissions` and `ipWhitelisted`; the "Withdrawal: OFF ✓" text; colour names
  `color.status.success/danger`; stories Default(SafeConfig), WithdrawEnabled,
  NoIpWhitelist(warning)
@ row CMP-175 KeyPermissionBadge (Atom, securi ‖ Gap
  no state for "not checked" or "overdue" (a defaulted `false` reads OFF); none of the ticket's
  eight variants; a missing allowlist drawn as a warning, which the contract refuses in every
  environment (`22:2722-2726`); no home for the verdict line; colour names that are no tokens
@ row CMP-175 KeyPermissionBadge (Atom, securi ‖ Proposal
  served enums per facet; the `key` and `aggregate` scopes; the thirteen states above with their
  class tokens and the critical mark; the stories of §13; the edits of Appendix A
§ spec ‖ 2.2 CMP-176 AccountKeyRow — the row, blocked and
@ head 4
  Component · tokens
@ row state ‖ Component · tokens
  CMP-175 for a key-verification state, CMP-011 for any other
@ row key and rights ‖ Part
  key and rights
@ row key and rights ‖ Content
  the masked id with the rights and withdrawal facets: "...a1b2 · Trade · Withdrawal OFF ✓ ·
  verified 14:02 UTC"
@ row key and rights ‖ Component · tokens
  CMP-034; CMP-175 `inline`
@ row allowlist ‖ Component · tokens
  CMP-175 `inline`
@ row key age · rotation due ‖ Part
  key age · rotation due
@ row notice ‖ Content
  the blocked sentence, the disabled outcome, "Rotation in progress · old key usable until
  10:55:01 UTC" (`D02:578`), "Revoked at {hh:mm} UTC — delete it at Bybit" (`D02:1030`), the
  off-by-policy line
§ spec ‖ CMP-176: props
@ row `key` ‖ Prop
  `key`
@ row `key` ‖ Type
  the key's metadata: `key_id_masked`, `status`, `created_at`, `rotation_due_at`,
  `rotation_state`, `expires_at`, `last_verified_at` (`listApiKeys`, `22:2672-2679`;
  `22:16873-16900`)
@ row `facets` ‖ Type
  the CMP-175 `key` states of withdrawal, rights, allowlist and expiry
@ row `facets` ‖ Rule
  per key from the security summary once G-1 serves it (O-A, `D02:1211`); until then each failure
  form is a target state stamped "not yet served — G-1, #895 / #896" (`D02:408-410`)
@ row `menu` ‖ Rule
  `ask` is the step-up line before the press, the item's second line (`D02:421-427`);
  `disabledReason` is a registered key, rendered as the second line, T2 per §10.1
§ spec ‖ CMP-176: the state slot — words, precedence and
@ prose
  One badge, the worst state that applies (`D02:365-366`), in this precedence — E27-D02's, with
  four PROPOSED additions: "Expired at Bybit" and "IP allowlist: none set" (BQ-5), "Off by policy"
  (BQ-7) and D4's "Withdrawal: not checked" as a row state.
@ prose
  BLOCKED › Key refused by Bybit · Expired at Bybit › IP allowlist: no match · none set › Down ›
  Off by policy › Check overdue · Withdrawal: not checked › Rotation overdue › Degraded › Rotation
  due · Bybit expiry › No key › Disabled › OK.
@ prose
  A key-verification state is a CMP-175 badge, so every verdict word lives in that one component
  (BQ-5); every other state is a CMP-011 chip with E27-D02's words (`D02:1099`).
@ prose
  A facet that sets the state still shows in its own cell, because `14` requires the permissions
  and allowlist columns as well as the state (`14:2514`); both come from CMP-175, so they never
  disagree.
@ row "BLOCKED — fund right found" ‖ State word
  "BLOCKED — fund right found"
@ row "BLOCKED — fund right found" ‖ Component
  CMP-175
@ row "Key refused by Bybit" ‖ State word
  "Key refused by Bybit"
@ row "Expired at Bybit" ‖ Component
  CMP-175
@ row "IP allowlist: no match" · "IP allowlist ‖ Component
  CMP-175
@ row "Check overdue — last passed {hh:mm} UTC ‖ Component
  CMP-175
@ row "Withdrawal: not checked" ‖ State word
  "Withdrawal: not checked"
@ row "Withdrawal: not checked" ‖ Component
  CMP-175
@ row "Bybit expiry in {n} d" ‖ Component
  CMP-175
@ row "No key — inactive" ‖ State word
  "No key — inactive"
§ spec ‖ CMP-176: blocked — the danger treatment (frame 1
@ prose
  - **Line 1.** The CMP-175 critical badge in the state slot, and [Start the compromise response]
  (CMP-001 secondary) before [Actions for sub_002 · LIVE]: first in the row's Tab order; it opens
  SCR-128's ordered card (D9, `D02:195`).
@ prose
  - **Line 2.** The notice, spanning the three facts: "This key can now withdraw or transfer — it
  was changed at Bybit.
@ prose
  - **Never quieter.** It is not dismissible; Rotate key… on this key is T2 `keys.compromise_path`
  (`D02:316`; T2 per §10.1); the shell announcer speaks it once, assertively (D21).
@ prose
  Until G-1 attributes the failure to a key, the row form is a target state stamped "not yet
  served — G-1, #895 / #896" on the board's annotation layer, and the banner's frame adds "Find
  the key in the audit log: action `account.tested`." (`D02:408-410`).
§ spec ‖ CMP-176: disabled — two forms, both at full text
@ head 5
  Tokens
§ spec ‖ CMP-176: tokens (dark; light by the same names)
@ heading
  #### CMP-176: tokens (dark; light by the same names)
@ head 2
  Tokens
§ spec ‖ CMP-176: current → gap → proposal
@ row CMP-176 AccountKeyRow (Molecule) ‖ Current (`15:2051-2057`)
  `account` · `onRotateKey` · `onRevoke` · `onEditProfile`; tokens "inherits CMP-106 ProfileBadge
  + CMP-175"; stories Default, RotatingKey, Revoked; no A11y line
§ spec ‖ 2.3 CMP-034 MaskedValue — permanently masked (AC
@ heading
  ### 2.3 CMP-034 MaskedValue — permanently masked (AC4)
@ prose
  Binding now: C-2.7 keeps plaintext inside the secrets module, and C-12.2 lets a response carry
  only key metadata — label, masked id, permissions, environment (`CON:136-140`, `CON:747-757`;
  `SECR:15`; main-orchestrator ruling, 2026-10-24 14:22Z, [LANE-hcl49], on BQ-8).
@ head 3
  Proposed (no reveal)
@ row Heading ‖ Current (`15:371-379`)
  "MaskedValue ("secret reveal")" (`15:371`)
@ row Heading ‖ Proposed (no reveal)
  "MaskedValue (historical name "secret reveal": permanently masked, no reveal)": the old name
  kept and annotated
@ row Purpose ‖ Current (`15:371-379`)
  "masked API key/secret display with reveal toggle (admin key screens)" (`15:373`)
@ row Purpose ‖ Proposed (no reveal)
  the server's masked key id, `...{last4}` from `key_id_masked`, as plain text wherever a key is
  named: the accounts list, the add, edit and rotate flows, the key table, the revoke dialog's
  title, the drawer and the setup checklist; it never receives a full value or a secret, so there
  is nothing to show and no control
@ row Props ‖ Current (`15:371-379`)
  `value` (a value the client holds in the current flow) · `label` · `revealed?` ·
  `onToggleReveal` · `autoHideMs?` · `copyable?` (`15:374`)
@ row Props ‖ Proposed (no reveal)
  `maskedId: string`, the served `key_id_masked`, `...` plus 4 characters (`22:16879-16882`), any
  other value rendering nothing and warning without echoing it · `label: string` ("API key"; names
  the group)
@ row States ‖ Current (`15:371-379`)
  masked (an 8-character mask), revealed, expiring, copied (`15:375`)
@ row States ‖ Proposed (no reveal)
  masked, its only state; with no key its host renders no CMP-034 (the row reads "No key —
  inactive")
@ row A11y ‖ Proposed (no reveal)
  `role="group"` named by `label`; the `...` is `aria-hidden` behind a visually hidden "ending
  in", so it reads "API key, ending in a1b2"; one description node per page, in the DOM at mount,
  which every CMP-034 on the page names by `aria-describedby` (one node, many pointers, as BQ-9's
  KEK notice), says the value is write-only and can't be shown (below); not focusable, no control,
  no timer, no live region
@ row Tokens ‖ Field
  Tokens
@ row Tokens ‖ Current (`15:371-379`)
  a box on `color.surface.raised` with a hairline; the value `type.num.base`; the mask
  `color.text.secondary`; the countdown `color.text.tertiary` (`15:377`)
@ row Storybook ‖ Current (`15:371-379`)
  Masked, Revealed, AutoHideCountdown, Copyable (`15:378`)
@ row Storybook ‖ Proposed (no reveal)
  Default (on a row), InDialog, InTableCell, WithDescription, NonMaskedValueRendersNothing,
  ForcedColors
@ row Tests ‖ Proposed (no reveal)
  unit (only `...` plus 4 characters renders), visual, axe; a regression that no attribute,
  `title`, data attribute, accessible name or hidden node holds more than the masked id
@ prose
  **The description** is the deck's `e27.cmp034.description` (§12.1), PROPOSED: "Shows the last 4
  characters of the key ID only.
@ prose
  The full key and its secret are write-only and can't be shown anywhere in CandleViewer." One
  node per page holds it, in the DOM at mount, and every CMP-034 on the page points at it by
  `aria-describedby` (one node, many pointers), so a page that names several keys carries it once;
  a screen reader meets it with a key id, and it never names a control.
@ prose
  The accessible name is `e27.cmp034.name`, "API key, ending in a1b2" in frame 6.
@ prose
  **Why the reveal is deliberately absent** (the rationale the entry records, AC4).
@ prose
  C-2.7 keeps every secret and decrypted key out of any API response, WS frame and frontend
  bundle, the secrets module exposing signing and metadata reads only (`CON:136-140`); C-12.2 and
  `SECR:15` let a response carry only key metadata; `listApiKeys` returns "metadata only" and
  `key_id_masked` holds at most the last 4 characters, the rest never stored in clear
  (`22:2677-2678`, `22:16879-16882`; KV-I07, `TM:256`); and US-ACCT-002 asks for "no reveal
  control anywhere in the app or API" (`11:344`).
@ prose
  A reveal path is a threat in itself — KV-I06 (`TM:255`), SR-E27-11 (`TM:664`), probes recorded
  as `api_key.reveal_attempt` (`ACT:139`) — and E27-D02's D13 and the memo's AD-11 bind it
  (`D02:199`, `MEMO:407`).
@ prose
  The ticket names "a masked value that implies a reveal is available" among the
  misrepresentations that cause a wrong decision (its Security notes): a box, a toggle, a timer or
  a copy control on a masked id would imply exactly that, so all four are gone, and the old name
  stays only as an annotated historical name.
@ prose
  **What it supersedes.** E05-D02 respecified CMP-034 (#4322) as a time-limited display of a value
  the client holds in the current flow on SCR-126 and SCR-127 (rules S1–S7, `E05F:748-795`),
  flagged to the security engineer for E05-X02 (G19, `E05F:448-453`).
@ prose
  Under BQ-8 nothing on those screens displays a client-held secret: entry is CMP-201's write-only
  variant (below) and a stored key is CMP-034's masked id.
§ spec ‖ CMP-201 PasswordField — the write-only variant (
@ heading
  #### CMP-201 PasswordField — the write-only variant (BQ-8 rider)
@ prose
  `15:2414` offers neither the autocomplete suppression nor the lock-down E27-D02 requires on a
  key field (`D02:532-536`): `showReveal` defaults to `true`, and `autoComplete` takes only the
  two password values.
@ prose
  Secret entry therefore takes a `writeOnly` variant of CMP-201, PROPOSED, never a new component.
@ row Purpose ‖ Current (`15:2411-2418`)
  "password input with a reveal toggle, caps-lock warning and `autocomplete` wiring" (`15:2413`)
@ row Purpose ‖ Proposed (the `writeOnly
  + a `writeOnly` variant for an API key or secret: SCR-126's key step, SCR-127 stage 2 and
  SCR-016 step 3 (`D02:453-456`, `D02:545-547`, `D02:855`)
@ row Props ‖ Current (`15:2411-2418`)
  `value` · `onChange` · `autoComplete: "current-password" | "new-password"` · `showReveal?:
  boolean = true` · `error?` (`15:2414`)
@ row Behaviour ‖ Proposed (the `writeOnly
  `type=password` always, never re-filled; paste allowed, never suppressed (`15:2415`); read-only,
  never `disabled`, while "Verify and save" is busy (`D02:484`); cleared on Cancel, on leaving the
  page, on a cancelled, expired or third-failed step-up, on the idle lock (SCR-005), at absolute
  session expiry and on sign-out (`22:11915-11916`), on CP-5's refusal and on the environment, UID
  and expiry refusals (`D02:511-518`), and after a successful save
@ row A11y ‖ Current (`15:2411-2418`)
  a "Show password" / "Hide password" toggle with `aria-pressed`; a polite caps-lock warning;
  paste never suppressed (`15:2415`)
@ row A11y ‖ Proposed (the `writeOnly
  no toggle in the DOM; the description — "value is write-only" for the key, CP-1's sentence for
  the secret (`D02:1100`) — in the DOM at mount through `aria-describedby` (`14:2537`); the
  caps-lock warning kept; a format error inline on press: key 8–128 and secret 8–256 characters
  (`22:16906-16907`)
@ row Leak rules ‖ Current (`15:2411-2418`)
  — (E05-D02's S4–S7 sit with CMP-034, `E05F:779-789`)
@ row Leak rules ‖ Proposed (the `writeOnly
  moved here: the value lives only in the input's value — never an attribute, a `title`, a data
  attribute, the accessible name or a hidden node — and print shows bullets (S4); no log,
  analytics event, audit record, error report or telemetry carries the value, its length or
  anything derived from it (S5; C-12.2, C-12.6); it is what the user typed in this flow, before it
  is sent, and after a save the screen shows only the masked id (S6); it leaves state on unmount
  and after a successful submit, and never enters browser storage, a URL, an autofill store or the
  undo history (S7)
@ row Tokens ‖ Field
  Tokens
@ row Storybook ‖ Current (`15:2411-2418`)
  Default, Revealed, CapsLockOn, WithError (`15:2417`)
@ prose
  **Riders.** CMP-035 drops "secret auto-hide" from its purpose (`15:383`): with no display of a
  secret there is no timer to run (§2.4).
@ prose
  CMP-033 keeps its props, and its purpose drops "API key display" (`15:363`): on the key screens
  it copies only the egress IP, their one copy control (D6, `D02:192`; KV-I11, `TM:260`), and
  never a key id, a UID or a secret.
@ row CMP-033 CopyButton (Atom) ‖ Current (`15:361-369`)
  "copy-to-clipboard affordance (API key display, audit record id, order id)"; stories Default,
  CopiedState
@ row CMP-033 CopyButton (Atom) ‖ Gap
  it names key display, which the key screens never offer (KV-I11)
@ row CMP-033 CopyButton (Atom) ‖ Proposal
  the egress IP as the key screens' only copy; + the EgressIp story; the edits of Appendix A
§ spec ‖ 2.4 The extensions — CMP-028, CMP-035, CMP-044,
@ head 4
  Proposed: props · a11y · tokens · Storybook
@ row CMP-028 Callout / Banner (Atom, composed ‖ Current (`15`)
  inline, non-global (`15:311-321`); `tone` with `danger` · `placement?` · `live?` · `icon?` ·
  `dismissible?` · `retry?` · `actions?` · `edge?` (`15:314`); danger is `role="alert"` unless
  `live` overrides it (`15:317`); the tone's subtle fill, a 2 px `border.thick` start edge and the
  glyph in its strong token (`15:318`)
@ row CMP-028 Callout / Banner (Atom, composed ‖ Gap
  the KEK notice must block and never dismiss, announce nothing (CMP-092's blocking row is the one
  announcement for the condition, `15:935`) and carry the stable id every blocked key control
  points at (one notice, many pointers: G-T2.5, `GATE:57-58`); `live="off"` silences a notice, but
  nothing keeps a danger notice undismissable or gives it that id
@ row CMP-028 Callout / Banner (Atom, composed ‖ Proposed: props · a11y ·
  + `blocking?: boolean` (danger only: `live="off"`, never dismissible, `id` required; D03-C16) ·
  `id?` · a11y: static text in page order, its first sentence the reason node · tokens: CMP-028's,
  plus a 2 px `border.thick` `color.status.danger.strong` border on all four sides on the blocking
  form · + DangerBlocking, DangerBlockingWithPointers, DangerBlockingForcedColors
@ row CMP-035 Countdown / Timer text (Atom): t ‖ Current (`15`)
  bar-close, re-auth expiry and "secret auto-hide" (`15:383`); `expiresAt` · `format` ·
  `onExpire?`; polite at thresholds (`15:385`); tokens `font.mono`, `color.text.warning`
  (`15:386`)
@ row CMP-035 Countdown / Timer text (Atom): t ‖ Gap
  the 900 s overlap needs the served end first and no client-clock claim, server-corrected time,
  no fault colour (its end is the expected path) and a stage that moves on the server's state,
  never at 0; neither token exists; the auto-hide went with the display (BQ-8)
@ row CMP-035 Countdown / Timer text (Atom): t ‖ Proposed: props · a11y ·
  + `showUntil?` · `serverOffsetMs?` · `announceAt?` (default 60, 10, 0) · `warnBelowS?` (`null`:
  no change) · `onExpire` never advances a server's state · a11y: `aria-live="off"`, polite at 60
  s and 10 s with the absolute time · tokens `type.num.base`, the time left
  `color.text.secondary`, the absolute time `color.text.primary` · + RotationOverlap,
  OverlapAt60s, OverlapAt10s, OverlapAtZero, ServerCorrected
@ row CMP-044 ConfirmDialog (Molecule): typed ‖ Current (`15`)
  `variant` (standard, typed, hold) · `typedConfirmValue?` · `role?` · `restatement?` ·
  `confirmDelayMs?` · `autoCancelMs?` · `busy?` (`15:476`); the typed Confirm natively disabled
  until the summary loads and the field matches (`15:477`); Cancel first, the hold variant's
  keyboard path and `Enter` in the typed field never confirming (`15:478`); the destructive
  Confirm a solid CMP-001 `danger` (`15:479`); its purpose says "delete API key" (`15:475`)
@ row CMP-044 ConfirmDialog (Molecule): typed ‖ Gap
  no consequence-loading state (no confirm may render until the summary loads, `14:2576`); no
  environment in the title; no rung, choice, ask line or marker until E42-D03's props land; a key
  is revoked here and never deleted at Bybit (`22:2847-2851`); the solid `danger` confirm's label
  is under the 7.0 hc-text bar (§9 `c175-solid-danger`), and a natively disabled confirm is not
  E42-D03's validity form (D03-C11, D03-C16)
@ row CMP-044 ConfirmDialog (Molecule): typed ‖ Proposed: props · a11y ·
  E42-D03's `rung`, `blastRadius`, `choices`, `stepUpState` and `auditCodes` consumed by name,
  PROPOSED, contract pending (`E42-D03:902`); its `acknowledge`, the `positions_unknown` tick, is
  never rendered on an E27 dialog: revoke, disable and delete take no acknowledge parameter
  (`22:14561-14564`), and the dead and fixable remedies are frame 56's resend and Close · +
  `consequenceState?` (loading or ready) · `environment?` · a11y: the confirm absent while
  loading, E42-D03's validity form (`E42-D03:542`) in place of the native `disabled` · tokens: the
  destructive confirm on `color.status.danger.subtle` with a 1 px `border.hairline`
  `color.status.danger.strong` border in place of the solid fill, the title `type.ui.heading-md`
  (D03-C16) · + ConsequencesLoading, ConsequencesLoadingSlow, EnvironmentSuffix,
  TypedLabelEnterNeverConfirms, ConfirmValidityHint, TwoChoicesNoneSelected, GatedChoice,
  ExchangeError
@ row CMP-066 Stepper (Molecule): the rotation ‖ Current (`15`)
  `steps: {label,status}[]` · `currentStep` (`15:684`); `aria-current`, list semantics, icon and
  text (`15:685`); tokens `color.status.*` (`15:686`)
@ row CMP-066 Stepper (Molecule): the rotation ‖ Gap
  no status set, no elapsed time, no page (`nav`) form, no collapsed form at 200 %; a bare status
  family instead of tokens
@ row CMP-066 Stepper (Molecule): the rotation ‖ Proposed: props · a11y ·
  E42-D05's unlanded `status` set (`todo`, `current`, `done`, `blocked`, `error`), `statusText?`
  and `navigable?` consumed by name, PROPOSED, contract pending (`E42-D05:921`) · + `meta?` (real
  elapsed time) · `as` (`list` or `nav`) · `collapsed?` · a11y: labelled stage regions, focus to
  the stage heading, `meta` never live, no progress bar · tokens: done
  `color.status.success.strong`, `error` `color.status.danger.strong`, current on
  `color.action.primary.default` · + Nav, NavSixSteps, RotationStages, RotationRefused, Collapsed
@ row CMP-178 SystemHealthTile (Molecule): per ‖ CMP
  CMP-178 SystemHealthTile (Molecule): per-key health (BQ-13)
@ row CMP-178 SystemHealthTile (Molecule): per ‖ Gap
  per-key health is a word with a heartbeat age inside a row or the drawer, not a tile; a tile's
  heading link would hand a non-owner an admin link
@ row CMP-178 SystemHealthTile (Molecule): per ‖ Proposed: props · a11y ·
  + `variant?` (`tile` or `inline`), the inline form taking one served `AccountHealth`
  (`22:16708-16737`); E42-D03's `state`, `asOf`, `lastGoodAt`, `detail` and `stopsWorking`
  consumed by name, PROPOSED, contract pending (`E42-D03:892-896`) · a11y: plain text, no region,
  heading or link, no live region of its own · tokens: the word `color.text.primary`, the age
  `color.text.secondary`, the glyph in the tone's strong token · + InlineHealthy, InlineDegraded,
  InlineDown, InlineNeverConnected, InlineInRow, InlineInDrawer
§ spec ‖ CMP-028 — the KEK-unavailable notice (BQ-9; fram
@ prose
  - **Anatomy.** The octagon (`icon/octagon`) · sentence 1, "Off while the credential key is
  unavailable.", which is the `keys.kek_unavailable` string and the node every blocked key
  control's `aria-describedby` points at · sentence 2, "Keys can't be added, tested or rotated
  until the KEK is back, and trading is off." (`D02:418-419`, `D02:1117`).
@ prose
  - **Where.** One per screen under its `h1` — SCR-125, SCR-126 and once in SCR-128's panel —
  beside the server's banner (D17, `D02:203`); on SCR-127 the wizard does not open and Rotate key…
  points at SCR-125's notice (`D02:585`).
@ prose
  - **The global banner is CMP-092, consumed.** Its blocking row carries the server's sentence,
  "Trading disabled: the credential key is unavailable." (`SYS:66`), and is the one announcement
  for the condition (`15:935`); the panel notice is CMP-028's `blocking` form and announces
  nothing.
@ prose
  - **Revoke stays enabled** (D17): the notice blocks Verify and save, Add a key, Rotate and Test
  (`D02:313`), never the revoke.
@ prose
  - **States.** One: present while `secrets.kek_unavailable` holds (`23:4262`), gone when it
  clears.
@ prose
  - **Tokens.** The fill `color.status.danger.subtle`; the text `color.text.primary`, 12.06 <!--
  audit:pairs.c175-danger-word.dark=12.06 --> / 14.64 <!--
  audit:pairs.c175-danger-word.light=14.64 --> / 13.66 <!--
  audit:pairs.c175-danger-word.high-contrast=13.66 --> (`c175-danger-word`); the octagon
  `color.status.danger.strong`, 7.83 <!-- audit:pairs.c175-danger-glyph.dark=7.83 --> / 3.85 <!--
  audit:pairs.c175-danger-glyph.light=3.85 --> / 7.83 <!--
  audit:pairs.c175-danger-glyph.high-contrast=7.83 --> (`c175-danger-glyph`); the 2 px
  `border.thick` border in `color.status.danger.strong` against the page, 10.42 <!--
  audit:pairs.page-danger-glyph.dark=10.42 --> / 4.73 <!--
  audit:pairs.page-danger-glyph.light=4.73 --> / 10.42 <!--
  audit:pairs.page-danger-glyph.high-contrast=10.42 --> (`page-danger-glyph`); sentence 1
  `type.ui.body-strong`, sentence 2 `type.ui.body`.
§ spec ‖ CMP-035 — the 900 s rotation overlap (BQ-10; fra
@ prose
  The old key ...e5f6 keeps working here until 10:55:01 UTC — 14:12 left — while requests in
  flight finish.
@ prose
  - **Announcements.** `aria-live="off"`; polite at 60 s and 10 s, each with the absolute time —
  the deck's `e27.scr127.overlap.at60` and `.at10` (§12.1), "1 minute left on the old key ...e5f6,
  until 10:55:01 UTC." and "10 seconds left on the old key ...e5f6, until 10:55:01 UTC." — and the
  end is CP-4's `e27.scr127.stage5.revoked`, polite once, with focus on stage 5's heading if the
  wizard is open (`D02:586-588`; D21, `D02:207`).
@ prose
  - **Colour.** None under a threshold (`warnBelowS: null`): the end of the overlap is the
  expected path, not a fault, and the warning text name is no token (`15:386`).
@ prose
  - **The row.** Only the absolute line, "Rotation in progress · old key usable until 10:55:01
  UTC" (`D02:578`), nothing ticking in a list (D21).
@ prose
  - **Tokens.** Both times `type.num.base`; the absolute `color.text.primary`, 13.27 <!--
  audit:pairs.dialog-text.dark=13.27 --> / 14.37 <!-- audit:pairs.dialog-text.light=14.37 --> /
  15.02 <!-- audit:pairs.dialog-text.high-contrast=15.02 --> (`dialog-text`); the time left
  `color.text.secondary`, 8.14 <!-- audit:pairs.dialog-secondary.dark=8.14 --> / 8.26 <!--
  audit:pairs.dialog-secondary.light=8.26 --> / 13.27 <!--
  audit:pairs.dialog-secondary.high-contrast=13.27 --> (`dialog-secondary`).
§ spec ‖ CMP-044 — the rungs as E27 uses them (BQ-11; fra
@ prose
  E42-D03's rung props are consumed by name, PROPOSED, contract pending (`E42-D03:902-904`):
  `rung` — rotate 1 (OQ-10), revoke 1 or, for the account's last active key, 3 (OQ-9), disable 3,
  delete 3 (`D02:272-285`) — `blastRadius` (the counts), `choices` (the two exposure radios),
  `stepUpState` (the ask line) and `auditCodes` (the marker).
@ row the typed token ‖ Delta
  the typed token
@ row the step-up ‖ Rule
  on the press a missing step-up opens SCR-006 (E09-D06's, consumed, an `alertdialog` with focus
  on the password) over this dialog; the request is held unchanged and sent once on success, and a
  cancel, the expiry, a third failure, the idle lock or the absolute session expiry sends nothing;
  a re-send that gets no answer (a network error or a timeout) may have executed, so the dialog
  never shows "Not saved — nothing was sent." and never re-sends: it reads the state back —
  `listApiKeys` after an import, rotate or revoke, `getExchangeAccount` after a disable or delete
  — and shows the outcome line or the busy line, with `e27.shared.resend_unconfirmed` meanwhile;
  the typed label lives in this dialog only, never a second typed field inside SCR-006
@ prose
  - **Tokens.** `color.surface.overlay`, `elevation.dialog` (never the primitive `elevation.4`),
  `radius.dialog`, `space.dialog.padding`; the title `type.ui.heading-md` and the consequences
  `type.ui.body`, both `color.text.primary`, 13.27 <!-- audit:pairs.dialog-text.dark=13.27 --> /
  14.37 <!-- audit:pairs.dialog-text.light=14.37 --> / 15.02 <!--
  audit:pairs.dialog-text.high-contrast=15.02 --> (`dialog-text`); the lead-in and the ask line
  `color.text.secondary`, 8.14 <!-- audit:pairs.dialog-secondary.dark=8.14 --> / 8.26 <!--
  audit:pairs.dialog-secondary.light=8.26 --> / 13.27 <!--
  audit:pairs.dialog-secondary.high-contrast=13.27 --> (`dialog-secondary`; `E42-D02:805`); the
  marker `color.text.tertiary`, 5.20 <!-- audit:pairs.dialog-tertiary.dark=5.20 --> / 5.44 <!--
  audit:pairs.dialog-tertiary.light=5.44 --> / 10.36 <!--
  audit:pairs.dialog-tertiary.high-contrast=10.36 --> (`dialog-tertiary`); the destructive confirm
  `color.text.primary` on `color.status.danger.subtle` (12.06 <!--
  audit:pairs.c175-danger-word.dark=12.06 --> / 14.64 <!--
  audit:pairs.c175-danger-word.light=14.64 --> / 13.66 <!--
  audit:pairs.c175-danger-word.high-contrast=13.66 -->, `c175-danger-word`) with a 1 px
  `border.hairline` `color.status.danger.strong` border against the dialog (`E42-D05:227`), 8.61
  <!-- audit:pairs.step-refused.dark=8.61 --> / 3.78 <!-- audit:pairs.step-refused.light=3.78 -->
  / 8.61 <!-- audit:pairs.step-refused.high-contrast=8.61 --> (`step-refused`; E42-D02 D3,
  `E42-D02:129`); Cancel, a CMP-001 secondary, 10.17 <!-- audit:pairs.secondary-button.dark=10.17
  --> / 12.82 <!-- audit:pairs.secondary-button.light=12.82 --> / 11.51 <!--
  audit:pairs.secondary-button.high-contrast=11.51 --> (`secondary-button`); the typed field
  CMP-007's (§2.3); focus 6.15 <!-- audit:pairs.ring-dialog.dark=6.15 --> / 5.39 <!--
  audit:pairs.ring-dialog.light=5.39 --> / 15.99 <!-- audit:pairs.ring-dialog.high-contrast=15.99
  --> (`ring-dialog`).
§ spec ‖ CMP-066 — one stepper, list or nav (BQ-12; frame
@ row SCR-126's page ‖ Steps
  1 Register the account · 2 Add its API key
@ prose
  - **Tokens.** Done `color.status.success.strong`, 8.69 <!-- audit:pairs.step-done.dark=8.69 -->
  / 3.11 <!-- audit:pairs.step-done.light=3.11 --> / 8.69 <!--
  audit:pairs.step-done.high-contrast=8.69 --> in a dialog (`step-done`); `error`
  `color.status.danger.strong`, 8.61 <!-- audit:pairs.step-refused.dark=8.61 --> / 3.78 <!--
  audit:pairs.step-refused.light=3.78 --> / 8.61 <!-- audit:pairs.step-refused.high-contrast=8.61
  --> (`step-refused`); current: a `color.action.primary.default` marker, its numeral
  `color.text.on-action`, 4.76 <!-- audit:pairs.primary-button.dark=4.76 --> / 4.76 <!--
  audit:pairs.primary-button.light=4.76 --> / 7.45 <!--
  audit:pairs.primary-button.high-contrast=7.45 --> (`primary-button`), its label
  `type.ui.body-strong` in `color.text.primary`; `todo`: a 1 px `color.text.tertiary` outline,
  5.20 <!-- audit:pairs.dialog-tertiary.dark=5.20 --> / 5.44 <!--
  audit:pairs.dialog-tertiary.light=5.44 --> / 10.36 <!--
  audit:pairs.dialog-tertiary.high-contrast=10.36 --> (`dialog-tertiary`), its numeral and label
  `color.text.secondary`; connectors `border.hairline` in `color.border.default`, decorative;
  `meta` `type.num.base` in `color.text.secondary`.
§ spec ‖ CMP-178 — per-key health, inline (BQ-13; frames
@ heading
  #### CMP-178 — per-key health, inline (BQ-13; frames 6, 16 and 62–71)
@ prose
  - **A11y.** Plain text in its cell: no region, heading or link, so not CMP-210, whose chips link
  to admin screens (`15:2493-2499`).
@ prose
  - **Tokens.** The word `type.ui.body`, `color.text.primary`; the age `type.num.base`,
  `color.text.secondary`; the glyph `size.icon` in `color.status.success.strong` (9.40 <!--
  audit:pairs.row-pass-glyph.dark=9.40 --> / 3.39 <!-- audit:pairs.row-pass-glyph.light=3.39 --> /
  9.40 <!-- audit:pairs.row-pass-glyph.high-contrast=9.40 --> on a row, `row-pass-glyph`),
  `color.status.warning.strong` (11.00 <!-- audit:pairs.row-warning-glyph.dark=11.00 --> / 4.11
  <!-- audit:pairs.row-warning-glyph.light=4.11 --> / 11.00 <!--
  audit:pairs.row-warning-glyph.high-contrast=11.00 -->, `row-warning-glyph`) or
  `color.status.danger.strong` (9.32 <!-- audit:pairs.c175-critical-border.dark=9.32 --> / 4.11
  <!-- audit:pairs.c175-critical-border.light=4.11 --> / 9.32 <!--
  audit:pairs.c175-critical-border.high-contrast=9.32 -->, the `c175-critical-border` pair); in
  the drawer `step-done`, `step-warning` and `step-refused`.
@ prose
  - **Used in** CMP-176's line 2 and SCR-079's "Key and health" block (`D02:786`); a non-owner's
  drawer shows the same words and nothing else of the key (`D02:806-808`).
§ spec ‖ 2.5 The other homes (AC6) — CMP-011, CMP-201, CM
@ heading
  ### 2.5 The other homes (AC6) — CMP-011, CMP-201, CMP-203, CMP-033 and the compositions
@ row the withdrawal verdict line ‖ E27-D02 element
  the withdrawal verdict line
@ row the withdrawal verdict line ‖ Home
  CMP-175, `aggregate` scope
@ row the key gate's check list ‖ E27-D02 element
  the key gate's check list
@ row the record's state ‖ Home
  CMP-175's badge or a CMP-011 chip (HD3)
@ row secret and key entry ‖ E27-D02 element
  secret and key entry
@ row secret and key entry ‖ Home
  CMP-201's `writeOnly` variant inside CMP-040
@ row every key id ‖ E27-D02 element
  every key id
@ row every key id ‖ Home
  CMP-034
@ row the egress IP's copy ‖ Extension or rule
  the key screens' one copy control
@ row the allowlist row; the drawer's key bloc ‖ E27-D02 element
  the allowlist row; the drawer's key block
@ row per-key health ‖ E27-D02 element
  per-key health
§ spec ‖ CMP-203 RequirementChecklist — the key gate's ch
@ heading
  #### CMP-203 RequirementChecklist — the key gate's check list (frame 3)
@ prose
  The same list runs on SCR-126's result card, SCR-127's stage 3, the Test dialog and SCR-016's
  step 3 (`D02:233-258`): one row per check of the key gate in the pipeline's order, "{check}:
  {outcome}" (`e27.checks.row`), the outcome a word with its glyph repeating it; a pass that
  carries a served warning keeps the word and takes the triangle (HD17).
@ head 4
  Tokens (§9)
@ row CMP-203 RequirementChecklist (Atom) ‖ Current (`15:2429-2435`)
  `items: {label, met}[]` for SCR-004's password rules; met or not met in words; the whole list
  `aria-live="polite"`; tokens `color.status.success` and `color.text.muted`, neither a token
@ row CMP-203 RequirementChecklist (Atom) ‖ Gap
  two outcomes cannot say "not checked", which must never read as a pass, nor a pass that carries
  a served warning (`22:16996-17003`); no detail line for a rule's words or a passed value; a
  list-wide live region would announce every row, where the key gate's host announces its verdict
  once (`D02:235-238`)
@ row CMP-203 RequirementChecklist (Atom) ‖ Proposal
  + `checks: {label, outcome: "passed"|"failed"|"not_checked", warning?:
  "key_expiring_soon"|"clock_skew", detail?}[]` beside `items` · + `live?` (default `true`;
  `false` for the key gate) · a11y: each row "{check}: {outcome}" in words, its glyph
  `aria-hidden`; a check that did not run reads "not checked"; a passed check with a served
  `warning` reads "passed with a warning — {detail}" beside the triangle (HD17) · tokens: passed
  `color.status.success.strong`, passed with a warning `color.status.warning.strong`, failed
  `color.status.danger.strong`, not checked `color.text.secondary`, words `color.text.primary`,
  the detail `color.text.secondary` · + KeyGateAllPassed, KeyGateRefusedRightsNotRead,
  KeyGateMixed, KeyGatePassedWithWarnings, KeyGateNotLive (§13)
§ spec ‖ 2.6 The cross-screen pattern frames (E27-D02 fra
@ prose
  Frame 2 is drawn in its `aggregate` forms on board 01 beside CMP-175's key forms; frames 3–5 sit
  on board 03 with the component specimens.
@ prose
  Light binds the same token names through `semantic-light`.
@ head 4
  Hi-fi (dark; light by token)
@ head 5
  Tokens
@ head 6
  Copy keys
@ row 2 ‖ Frame (E27-D02 §7)
  `Pattern / withdrawal verdict: dated, overdue, failed, unavailable, no keys`
@ row 2 ‖ Hi-fi (dark; light by to
  CMP-175 `aggregate` in its eight forms (§2.1), one 32 px line under the `h1` on
  `color.surface.app`: dated with the check, "Withdrawal: OFF on all 4 accounts with a key ✓ ·
  verified 14:02 UTC"; overdue with the clock; failed and unavailable with the octagon; read
  failed and no keys with the dash; loading as a static skeleton line, never OFF; cleared back to
  the dated form with the new time, never a claim that trading is on. Each negated form sits under
  CMP-092's blocking row with the server's sentence, and the line never computes a verdict of its
  own (`D02:212-230`)
@ row 3 ‖ Hi-fi (dark; light by to
  CMP-203's `checks` form (§2.5) on demo-1's key: the nine rows in the pipeline's order, all
  passed, Withdrawal and transfer reading "OFF ✓ · verified 14:02 UTC" with the check's time
  (D03-C15); a refused variant with "Withdrawal and transfer" failed and every later row "not
  checked"; a mixed variant with the allowlist failed and its whitelist read; a warning variant,
  every row passed and two of them carrying a served warning on the triangle (HD17) — Bybit expiry
  "passed with a warning — Bybit expiry 2026-11-01 UTC, in 9 d" and Signed probe and clock "passed
  with a warning — clock offset 640 ms, over the 500 ms limit"; the Environment and UID rows
  always name the frame's own account (C-2.11)
@ row 3 ‖ Copy keys
  `e27.checks.row` · `e27.checks.names` · `e27.checks.not_checked` · `e27.checks.env.passed` ·
  `e27.checks.withdrawal.passed` · `e27.checks.rights.passed` · `e27.checks.trade.passed` ·
  `e27.checks.uta.passed` · `e27.checks.uid.passed` · `e27.checks.allowlist.passed` ·
  `e27.checks.expiry.passed` · `e27.checks.expiry.expiring` · `e27.checks.probe.passed` ·
  `e27.checks.probe.skew`
@ row 4 ‖ Frame (E27-D02 §7)
  `Pattern / T2 anatomy with the E27 state keys`
@ row 4 ‖ Hi-fi (dark; light by to
  four gated controls in E09-D09's T2 form — a menu item ("Rotate key…" under
  `keys.kek_unavailable`), a button ("Verify and save"), a radio ("Leave positions and orders
  open" under `accounts.stop_missing`) and a checklist step (`rbac.owner_only`) — each with the
  `lock` leading its full label, `aria-disabled="true"` and its reason as the 2a second line,
  inside CMP-079 RbacGate; beside them an unmet rung confirm in E42-D03's validity form (no lock,
  no key) and the rejected dimmed look, drawn only as a struck-through specimen (§9 `t2-dimmed`);
  the ten PROPOSED E27 keys of §12.2 listed with their strings
@ row 4 ‖ Copy keys
  the reason keys of §12.2 · `e27.scr129.hint.choose` · `e27.scr129.hint.typed`
@ row 5 ‖ Hi-fi (dark; light by to
  E42-D02 §4.1's anatomy as E27 applies it (§2.4, BQ-11): rung 1 — "Revoke key ...e5f6 on sub_002
  · LIVE", its one consequence, "It stops working here at once; sub_002 keeps trading on ...d9e0.
  It still works at Bybit until you delete it in Bybit's dashboard.", the ask line and the marker,
  [Cancel] [Revoke key ...e5f6 here] enabled at once; rung 3 — "Disable sub_002 · LIVE", the
  consequences with their counts, the two choices none checked, "Type sub_002 to confirm:", the
  ask stamped "not yet served — G-8, #895 / #898", "Recorded in the audit log", the confirm in the
  validity form with its hint; between them the loading state, Cancel alone and no confirm in the
  DOM (`D02:260-291`)
@ row 5 ‖ Copy keys
  `e27.scr129.revoke.title` · `e27.scr129.revoke.not_last` · `e27.scr129.revoke.confirm` ·
  `e27.scr129.disable.title` · `e27.scr129.typed` · `e27.shared.ask` · `e27.shell.grace.keys` ·
  `e27.scr129.marker` · `e27.scr129.marker.revoke` · `e27.scr129.loading` ·
  `e27.scr129.hint.choose` · `e27.scr129.hint.typed` · `e27.shared.cancel`
§ spec ‖ 3. SCR-125 — Bybit accounts list (`/admin/accoun
@ prose
  - **Strings.** Each row names its §12 keys.
@ prose
  - **Tokens.** Each element's token is named once.
@ prose
  Fixture values only (the Key); every time in UTC.
§ spec ‖ 3.1 Anatomy at 1280 × 800 and the redline (frame
@ prose
  Frame 6's dated withdrawal words take two text lines in their cell, so the list runs past the
  StatusBar's top: blocks K and L are reached by scrolling, and the board draws them as the page's
  continuation under the 1280 × 800 viewport line.
@ head 3
  Size · tokens
@ row C Band, rule and strip (consumed) ‖ Content and copy
  the band "Admin area · Accounts", with the `keys` grace line "Still trusted for key changes ·
  02:14" at its right end while one is live (variant (b)); the 4 px rule; the strip region "Needs
  your action", one line when empty: "Nothing needs your action"
@ row C Band, rule and strip (consumed) ‖ Size · tokens
  band y 48–80 and strip y 84–116, one 32 px row each; the rule y 80–84; E42-D03 §4's tokens: the
  band `color.surface.raised` and the rule `color.text.tertiary` (DS-1 and DS-2's interim
  bindings)
@ row D PageHeader (CMP-088) ‖ Content and copy
  `h1` "Bybit accounts and keys", the skip link's target (CMP-085); the meta "As of 14:02:11 UTC"
  (`e27.shell.meta`: E42-D03's `meta.asof` with the zone at the time); "+ Add account" (CMP-001
  `primary`)
@ row E Verdict line ‖ Content and copy
  CMP-175 `aggregate` (BQ-5) in one of frame 2's forms (§2.6) — frame 6: "Withdrawal: OFF on all 4
  accounts with a key ✓ · verified 14:02 UTC"; never dismissible, always dated in UTC, never OFF
  without a time; it reads the server's notices and computes no verdict of its own
@ row H Table head (CMP-049) ‖ Content and copy
  a plain `table` with a visually hidden `caption` (the `h2` is its visible twin); two header
  rows: "label · UID · env" · "state" · "key · rights" · "actions", then "IP allowlist" · "key age
  · rotation due" · "health" under the last three
@ row J Records (CMP-176) ‖ Size · tokens
  two lines of 32 px `min-height` per record on `color.surface.raised`; in frame 6 line 1 is about
  44 px, because cell 3's dated withdrawal word takes two text lines in its 272 px column (2 ×
  18.2 px of `type.ui.body`, plus the 4 px block padding twice), breaking before "verified", which
  stays whole — never truncated and never undated (D3, AD-3) — so a record is about 76 px:
  CMP-176's record fill (§2.2) takes the place of CMP-049's zebra (`15:531`), so every pair sits
  on the surface §9 measures; a 1 px `color.border.default` rule between records (`hairline`,
  decorative); LIVE's group row y 352–384 and its records y 384–612; DEMO's group row y 612–644
  and demo-1 y 644–720
@ row K Region "Key health and secrets policy" ‖ Block
  K Region "Key health and secrets policy"
@ prose
  **Focus and keys (R3).** Skip link → TopBar → NavRail → strip items → "+ Add account" → [Change]
  → per record, in order: [Start the compromise response] where the record is blocked, then
  Actions, then Details → the "Key health and secrets policy" button → RightRail → StatusBar
  (`D02:434-435`; `E42-D03:199-200`, `E42-D03:589`).
§ spec ‖ 3.2 The record (CMP-176) as this list draws it
@ head 4
  Tokens (§9)
@ row 2 ‖ Line 1
  the state: one badge, the worst that applies — CMP-175's badge for a key-verification state, a
  CMP-011 chip for any other (§2.2, HD3; the table below)
@ row 2 ‖ Line 2
  the allowlist facet, CMP-175 `key` (§2.1) — frame 6: "matches"
@ row 3 ‖ Line 1
  CMP-034's `...{last4}` (`type.num.base`), then the CMP-175 `key` facets for the trade right and
  the withdrawal check in their dated pass form (§2.1; AD-3) — frame 6: "...a1b2 · Trade ·
  Withdrawal OFF ✓ · verified 14:02 UTC", breaking before "verified" in the 272 px column (§3.1
  block J)
@ row 3 ‖ Line 2
  the key age and its rotation due date — frame 6: "41 d · due 2026-12-11 UTC"; the age's
  description carries its absolute date (`E42-D02:119`)
@ prose
  **The state** takes §2.2's precedence — E27-D02's words (`D02:1099`) in its order
  (`D02:365-366`) with four PROPOSED additions — and §2.2's components: CMP-175's own word for a
  key-verification state, so every verdict word lives in that one component (BQ-5; HD3), and a
  CMP-011 chip for every other state; line 2's CMP-175 facet repeats the allowlist state (§2.1).
@ prose
  Glyph names follow BQ-6; the slashed circle is E42-D03's `icon/slashed-circle`, the glyph of its
  own "Disabled" chip (`E42-D03:635-641`); the copy keys are §12.1's `e27.cmp175.*` and
  `e27.scr125.chip.*`.
@ row 1 ‖ State
  "BLOCKED — fund right found"
@ row 1 ‖ Component · class or var
  CMP-175 critical badge · octagon, with the critical mark: `font.weight.bold` and a 2 px
  `color.status.danger.strong` border (`border.thick`)
@ row 2 ‖ State
  "Key refused by Bybit" · "Expired at Bybit"
@ row 2 ‖ Component · class or var
  CMP-011 `danger` · octagon; CMP-175 failed badge · octagon
@ row 3 ‖ Component · class or var
  CMP-175 failed badge · octagon: a refusal, never a warning (AD-4, `MEMO:400`)
@ row 6 ‖ State
  "Check overdue — last passed {hh:mm} UTC" · "Withdrawal: not checked"
@ row 6 ‖ Component · class or var
  CMP-175 time-warning badge · clock; CMP-175 unknown badge · dash, never OFF (D4)
@ row 9 ‖ Component · class or var
  CMP-011 `warning` · triangle; CMP-175 warning badge · triangle; two clocks, two words (D7)
@ row 10 ‖ State
  "No key — inactive"
§ spec ‖ 3.3 The data and their producers
@ row each key's facts ‖ Datum
  each key's facts
@ row each key's facts ‖ Operation · field (`22`)
  `listApiKeys` (`22:2672-2690`): `key_id_masked`, `status`, `created_at` (the key age),
  `rotation_due_at`, `rotation_state`, `expires_at`, `last_verified_at` (`22:16873-16900`)
@ row each key's facts ‖ `x-rbac`
  `keys:read`
@ row the withdrawal and allowlist facets per ‖ Datum
  the withdrawal and allowlist facets per key
@ row the withdrawal and allowlist facets per ‖ Operation · field (`22`)
  `getSecuritySummary` (`22:13742-13758`) `keys[]`: `withdrawal_permission_present`,
  `ip_whitelist_matches_expected`, `last_verified_at` (`22:22011-22032`); the failing rule per key
  is G-1's (O-A, `D02:1211`)
@ row Test ‖ Operation · field (`22`)
  `testApiKey` (`22:2955-3002`): a failing verdict latches read-only and disarms the account, a
  pass changes neither; one test per key per minute, else `429`
@ row Test ‖ `x-rbac`
  `keys:read`
@ row the egress IP and every right as reporte ‖ `x-rbac`
  `keys:read`
§ spec ‖ 3.4 The hi-fi rows (frames 1 and 6–17)
@ head 4
  Hi-fi: layout and redline (dark; light by token)
@ head 6
  Tokens (§9)
@ head 7
  Copy keys (§12)
@ row 1 ‖ Hi-fi: layout and redlin
  §3.1's page with the shell redlined (blocks A–D, K and L); the band's `keys` grace line "Still
  trusted for key changes · 02:14", timed from the server's `step_up_expires_at` (variant (b));
  the strip with one item, "Rotation due for sub_002 in 12 d → Rotate", carrying its LIVE pill and
  "Attention:" in its accessible name (`D02:150`, `D02:390`); the route content is frame 6's
@ row 1 ‖ Copy keys (§12)
  `e27.shell.band`, `e27.shell.grace.keys`, `e27.shell.strip.title`,
  `e27.shell.strip.rotation_due`, `e27.shell.meta`, `e27.shell.footer` (consumed: E42-D03's
  `band.*`, `strip.*`, `meta.asof`, `footer.area_entered`, `E42-D03:608-610`); `e27.shell.h1`,
  `e27.shell.cta.add`
@ row 6 ‖ Components (variant · pr
  CMP-049 (`caption`; no `grid`) · CMP-176 ×4 (`state` ok) · CMP-011 `neutral` + check · CMP-034 ·
  CMP-175 `key` (verified, trade-only) and `aggregate` (dated) · CMP-178 inline (healthy) ·
  CMP-075 · CMP-041 · CMP-001
@ row 6 ‖ Copy keys (§12)
  `e27.shell.h1`, `e27.shell.cta.add`, `e27.scr125.verdict.dated`, `e27.shell.region.accounts`,
  `e27.scr125.cap.recorded`, `e27.scr125.table.caption`, `e27.scr125.table.headers`,
  `e27.scr125.group`, `e27.scr125.chip.ok`, `e27.scr125.row.age`, `e27.scr125.row.health`,
  `e27.scr125.row.actions`, `e27.scr125.row.details`; CMP-175's words (§2.1)
@ row 7 ‖ Hi-fi: layout and redlin
  the two header rows over one body row, a `td colspan="4"` with CMP-026 (2 × 32 px): "No Bybit
  accounts yet. Register your main account first; its sub-accounts follow."; "+ Add account" in
  the PageHeader is the one call to action; the verdict's no-keys form "No stored keys yet —
  nothing to check."; no capacity line; the strip's empty line
@ row 7 ‖ Components (variant · pr
  CMP-049 (`emptyState`) · CMP-026 (no-data, `cta` omitted) · CMP-175 `aggregate` (no keys)
@ row 8 ‖ Hi-fi: layout and redlin
  two nested states. Loading: the header rows over three CMP-015 records of two 32 px lines each,
  static under reduced motion, the table `aria-busy`, the verdict "Withdrawal verdict loading…",
  never OFF. Error: the header rows over one row, CMP-027 "Couldn't load the accounts — {detail}.
  [Retry]", and the verdict's read-failed form "Withdrawal verdict unavailable — the accounts
  could not be read."; in both the capacity line keeps its own read and state (`E42-D03:122`)
@ row 8 ‖ Components (variant · pr
  CMP-049 (`loading`, then `error` with its retry) · CMP-015 (`shape` row, `count` 3) · CMP-027
  (`retry`) · CMP-175 `aggregate`
@ row 8 ‖ Tokens (§9)
  the skeleton bars `color.surface.hover` on `color.surface.raised`, decorative (CMP-015's own
  `color.surface.skeleton` is not a token; this binding is PROPOSED to its owner, D03-C12); the
  error line `row-text`
@ row 9 ‖ Frame (E27-D02 §7)
  `SCR-125 / key expiring (<14 d): rotation due and Bybit expiry`
@ row 9 ‖ Hi-fi: layout and redlin
  frame 6 with two records changed: sub_002's chip "Rotation due in 12 d" over line 2 "78 d · due
  2026-11-04 UTC" (the age SCR-127's stage 1 states, `D02:567-568`), its details open with
  "Overdue never stops trading."; demo-1's chip "Bybit expiry in 9 d", its details (an inset) "The
  key stops working at Bybit on 2026-11-01 UTC — rotate before then."; the strip's item "Rotation
  due for sub_002 in 12 d → Rotate" (E42-D03's `strip.key_expiry` says "expires" for the policy
  clock, which D7 forbids: D03-C6, §14)
@ row 9 ‖ Components (variant · pr
  CMP-011 `warning` + triangle · CMP-175 `key` expiring for demo-1 (§2.1) · CMP-036 (details) ·
  CMP-021 (the strip item)
@ row 10 ‖ Frame (E27-D02 §7)
  `SCR-125 / within Bybit's 48 h new-key restriction`
@ row 10 ‖ Hi-fi: layout and redlin
  a freshly registered sub_002: the chip "No key — inactive"; cell 3 spans both lines with the
  account-level sentence routed in C-9, "Bybit's 48 h restriction applies to this account's first
  key; the time it lifts is not recorded. Demo trading is available meanwhile." (PROPOSED), never
  a computed time (AD-14); health reads "Not monitored yet" with the dash while `health` is `null`
  (§2.4; new, PROPOSED); the menu, an inset, opens on "Add a key…" (a keyless record only); the
  timed form waits for G-3 and is not drawn (`D02:1001-1003`)
@ row 10 ‖ Focus and announcements
  Actions → "Add a key…" opens SCR-126's key step
@ row 11 ‖ Hi-fi: layout and redlin
  (a) sub_001's menu open under its Actions button: a CMP-041 popover on `color.surface.overlay`,
  280 px wide, `elevation.popover`, `radius.card`, 32 px items in E27-D02's order — Edit… · Rotate
  key… · Test key… · Revoke key… · Suspected compromise… · Disable… · Delete (keeps history)… —
  Rotate and Revoke with the ask as a second line, "Asks for your password and a code" (or "Still
  trusted for key changes · 02:14"), Revoke on sub_001's only key adding "and the account's name"
  (`D02:426`), Disable and Delete with "Asks for your password, a code and the account's name",
  stamped "not yet served — G-8, #895 / #898"; (b) the Test dialog "Test sub_001's key ...c3d4 ·
  LIVE": CP-6's before-sentence as its description, [Cancel] (initial focus) [Run test]; while
  running, Run test busy; the result: a heading, the check list with sub_001's rows (LIVE, UID
  1234568; `D02:255-257`), "REST probe: passed · 118 ms" and "WebSocket: not checked"; the dismiss
  button then reads "Close" (`e27.shared.close`, new, PROPOSED); (c) an inset of the minute after
  this client's test: Run test and the menu's Test key… gated by `keys.test_throttled`, "One test
  per key per minute; next at 14:04:10 UTC.", the reason as the item's second line and under the
  dialog's buttons (2a); (d) an inset of a `429` because another session tested: "Tested at
  14:03:10 UTC; the next test can run at 14:04:10 UTC." (a refusal at the point of action, never
  gated)
@ row 11 ‖ Copy keys (§12)
  `e27.scr125.menu.items`, `e27.scr125.menu.ask.keys`, `e27.shell.grace.keys`,
  `e27.scr125.menu.ask.label`, `e27.scr125.test.title`, `e27.scr125.test.before` (CP-6),
  `e27.scr125.test.buttons`, `e27.shared.close`, `e27.scr125.test.result`,
  `e27.checks.rest_probe`, `e27.checks.ws_probe`, `e27.scr125.test.passed`,
  `e27.scr125.test.throttled`; reason `keys.test_throttled`
@ row 11 ‖ Focus and announcements
  Actions → `Enter` opens the menu on its first item; `↑` / `↓` reach a gated item without
  activating it, and `Enter` there re-shows the reason with one polite announcement; Test key…
  opens the dialog on Cancel → Run test; after the answer focus moves to the result heading; a
  refusal assertive once, a pass polite once; `Esc` closes and focus returns to Actions
  (`D02:429-437`, `D02:1049`)
@ row 13 ‖ Frame (E27-D02 §7)
  `SCR-125 / withdrawal permission detected: blocking error`
@ row 13 ‖ Hi-fi: layout and redlin
  block B holds CMP-092's blocking row "Trading disabled: a stored API key failed its check."
  (`SYS:71`), whose `href` opens the audit log filtered to `account.tested` with "Find the key in
  the audit log: action `account.tested`." (the served form today, `RB:51`); the verdict in its
  failed form, with the octagon; the other records as frames 9 and 16 draw them, so one list holds
  BLOCKED beside the ordinary warnings — Main "OK", sub_001 "Degraded — REST only" (triangle),
  demo-1 "Bybit expiry in 9 d" (triangle); sub_002's record in the danger treatment (BQ-7, §2.2):
  both lines on `color.status.danger.subtle`, a 4 px `color.status.danger.strong` inline-start
  rule on the label cell, the chip "BLOCKED — fund right found" with the critical mark, [Start the
  compromise response] (CMP-001 `secondary`) first in the actions cell, above Actions and Details,
  and line 2 one cell across cells 2–4: "This key can now withdraw or transfer — it was changed at
  Bybit. Trading is read-only for every account and off for sub_002."; never dismissible; the
  strip's first item routes to it, "Attention: LIVE — a key on sub_002 can move funds → Start the
  compromise response" (new, PROPOSED: E42-D03's `strip.withdrawal` says "remove it on Bybit",
  where C-12.12 deletes the key at Bybit, so D03-C7, §14); the menu, an inset, keeps Rotate key…
  gated by `keys.compromise_path` and Suspected compromise… live; until G-1 attributes the failure
  to a key, the record, its strip item and its gated Rotate are a target state stamped "not yet
  served — G-1, #895 / #896" (`D02:408-410`)
@ row 13 ‖ Components (variant · pr
  CMP-092 (`href`) · CMP-175 `aggregate` (failed) · CMP-176 blocked · CMP-175 critical badge
  (octagon, the critical mark) · CMP-011 `warning` + triangle (sub_001) · CMP-175 `key` expiring
  (demo-1) · CMP-178 inline (degraded) · CMP-001 · CMP-041 + CMP-079 + CMP-019 `lock`
@ row 13 ‖ Copy keys (§12)
  `e27.shell.banner.key_failed` (consumed, `SYS:71`), `e27.scr125.verdict.audit_hint`,
  `e27.shell.strip.withdrawal`, `e27.scr125.verdict.failed`, `e27.cmp175.withdrawal_detected`,
  `e27.scr125.blocked.line2`, `e27.scr125.blocked.action`, `e27.scr125.chip.degraded`,
  `e27.cmp175.expiring`; reason `keys.compromise_path`
@ row 14 ‖ Hi-fi: layout and redlin
  sub_001's record: the chip "IP allowlist: no match" over line 2's facet "no match" (an inset
  draws Main's empty whitelist, the facet "none set", §2.1); sub_001's details open with CD-3's
  CandleViewer-rule form, its last clause "then test again"; its address and [Copy] come only from
  a Test this client ran (frame 11; `KeyTestResult.verification.egress_ip`, `22:17135`), since no
  list field carries the address (`22:16873-16900`) and the notice names no key or account
  (`23:4270-4271`): before a Test they are the D03-G1 target state, stamped "not yet served —
  D03-G1, #896" (HD14), and after one CMP-033 sits on 203.0.113.10; a stored key failing the check
  latches read-only, so block B's blocking row and the verdict's failed form show too
  (`D02:410-412`); the record is a target state stamped "not yet served — G-1, #895 / #896"
@ row 14 ‖ Components (variant · pr
  CMP-175 failed badge and `key` facet, IP-mismatch and IP-missing (§2.1) · CMP-036 + CMP-033 ·
  CMP-092
@ row 14 ‖ Focus and announcements
  Details → Copy once a Test served the address ("Copied", polite, CMP-033's own); the re-test is
  Actions → Test key…; CMP-092's row is the one announcement
@ row 15 ‖ Frame (E27-D02 §7)
  `SCR-125 / key invalid`
@ row 15 ‖ Hi-fi: layout and redlin
  sub_002's record with key ...e5f6: the chip "Key refused by Bybit", which outranks the Down its
  health line shows; its details open: "Bybit no longer accepts key ...e5f6 — it signs nothing.
  Rotate it, or revoke it here if you deleted it at Bybit." (Rotate's precondition on an `invalid`
  key is G-5's and the server decides, `D02:414`); once the hourly check fails on it too, block B
  and the verdict's failed form show as in frame 14 (`RB:53`)
@ row 15 ‖ Focus and announcements
  the record's Details; the failed key announced once through the shell announcer, assertive
  (`D02:1078-1079`)
@ row 17 ‖ Hi-fi: layout and redlin
  block B holds CMP-092's blocking row "Trading disabled: the credential key is unavailable."
  (`SYS:66`); one CMP-028 panel notice under the `h1` (BQ-9: the danger tone, blocking, never
  dismissible, no live region, a stable `id`) with the octagon, "Off while the credential key is
  unavailable." then "Keys can't be added, tested or rotated until the KEK is back, and trading is
  off.", in y 176–240 so blocks E–L move down 64 px; in every menu Add a key…, Rotate key… and
  Test key… are gated by `keys.kek_unavailable`, the reason as their second line and their
  `aria-describedby` on the notice's `id` (one notice, many pointers; 2a); Revoke key… stays live
  (D17)
@ row 17 ‖ Copy keys (§12)
  `e27.shell.banner.kek` (consumed, `SYS:66`); the notice's first line is the reason
  `keys.kek_unavailable`; its second `e27.shared.kek_notice`
§ spec ‖ 4. SCR-126 — Add or edit a Bybit account, and SC
@ prose
  Board 06 nests frames 18–32 at 1280 × 800 in dark, with §4.1's redline first, and SCR-016's four
  frames as insets (BQ-1); light is bound by token and not drawn (§0: board 06 has no twin; the
  text is binding).
@ prose
  Both screens are comfortable (BQ-4; `16:114`); §3's rules for strings, tokens, gated controls,
  stamps and fixtures hold here.
§ spec ‖ 4.1 Anatomy at 1280 × 800 and the redline (frame
@ head 3
  Size · tokens
@ row B PageHeader (CMP-088) ‖ Content and copy
  `h1` "Add a Bybit account" at the left; at the right the CMP-066 `nav` stepper (BQ-12), "1
  Register the account ✓ · 2 Add its API key (current)": the done step with its check and its
  word, a link back to its step (CMP-021), and the current step `aria-current="step"`
@ row D Key-step heading ‖ Block
  D Key-step heading
@ row D Key-step heading ‖ Content and copy
  `h2` "API key for demo-1 · UID 9000001 · DEMO (this deployment)", the environment word as the
  CMP-075 pill
@ row E Instruction list ‖ Content and copy
  "Create the key in Bybit's dashboard with only:" and three items — "Contract trade — Order and
  Position (Derivatives — DerivativesTrade is allowed too)" · "no withdrawal or transfer right" ·
  "the IP allowlist below"; static text, never boxes the owner ticks (the memo's F-19, `MEMO:260`)
@ row F Allowlist row (CMP-036; BQ-14) ‖ Content and copy
  `dt` "IP allowlist"; `dd` CP-3 verbatim: "Set this key's IP allowlist in Bybit's dashboard to
  exactly 203.0.113.10 [Copy]. It can't be set here; CandleViewer only checks it." Before any
  check the address and its Copy are a target state, stamped "not yet served — D03-G1, #896"
  (BQ-15: only a verification result carries `egress_ip`); with no egress IP configured there is
  no Copy and no import can pass (D6); CMP-033 is the one copy control on the screen
@ row G API key field ‖ Block
  G API key field
@ row G API key field ‖ Content and copy
  CMP-040 (label "API key"; help "value is write-only", in the DOM at mount and linked by
  `aria-describedby`) on CMP-201's write-only variant (BQ-8, §2.3): `type=password`, autocomplete
  suppressed, cleared on leave, paste allowed, no reveal control, never re-filled
@ row H API secret field ‖ Block
  H API secret field
@ row H API secret field ‖ Content and copy
  as G; label "API secret", help CP-1 verbatim: "Write-only: CandleViewer uses this secret to sign
  orders, and no one can see it again — not you, not an admin. If it is lost, create a new key at
  Bybit."
@ row I Ask line and audit marker ‖ Content and copy
  "You'll confirm with your password and a code." — inside the `keys` grace window "Still trusted
  for key changes · 02:14", timed by the server's `step_up_expires_at` — then CMP-093's marker,
  last before the buttons: "Recorded in the audit log · API key imported (api_key.import)"
@ prose
  **Focus and keys (R3).** Skip link → strip → the stepper's done step → Copy → API key → API
  secret → Cancel → Verify and save (`D02:532-533`).
@ prose
  After an answer focus moves to the result heading; then the summary's controls, then the form
  card's stops again, so a refused key is fixed and verified again without going back
  (`D02:533-534`).
§ spec ‖ 4.2 The data and their producers
@ row import ‖ Operation · field (`22`)
  `createApiKey` (`22:2691-2842`), stored only if every check passes (`22:2696`);
  `CreateApiKeyRequest` (`22:16901-16914`): key 8–128 and secret 8–256 characters
@ row import ‖ `x-rbac` · step-up class
  `keys:manage` · `keys` (`SU:521`)
@ row edit ‖ `x-rbac` · step-up class
  `accounts:write`; `keys:read`
§ spec ‖ 4.3 The hi-fi rows (frames 18–32)
@ prose
  A refusal keeps the pasted values in their wells, masked, so "verify again" sends them as they
  are, except where a row says both fields clear (`D02:511-518`).
@ head 4
  Hi-fi: layout and redline (dark; light by token)
@ head 6
  Tokens (§9)
@ head 7
  Copy keys (§12)
@ row 18 ‖ Hi-fi: layout and redlin
  the stepper's step 1 current; the form card holds Label and Bybit UID (wells as block G, the UID
  `type.num.base`), Kind as two radios in a row ("Main account" · "Sub-account"), Parent for a sub
  only (this environment's main accounts), the environment as a CMP-036 row "DEMO (this
  deployment)" with the pill and no control (OQ-4), then [Cancel] [Register account]; filled for
  demo-1: demo-1 · 9000001 · Main account; once registered the account lists as "No key —
  inactive" (`11:320`) and step 2 opens
@ row 19 ‖ Frame (E27-D02 §7)
  `SCR-126 / paste the key: write-only fields and the allowlist row`
@ row 19 ‖ Hi-fi: layout and redlin
  §4.1 exactly: demo-1's key step, the egress-IP stamp on block F
@ row 19 ‖ Components (variant · pr
  CMP-087 · CMP-088 · CMP-066 `nav` · CMP-050 · CMP-075 · CMP-036 + CMP-033 · CMP-040 + CMP-201
  write-only · CMP-093 (its visible marker) · CMP-001
@ row 19 ‖ Copy keys (§12)
  `e27.scr126.key.h2`, `e27.scr126.key.instructions`, `e27.scr126.allowlist.label`,
  `e27.scr126.allowlist.help` (CP-3), `e27.scr126.key.label`, `e27.scr126.secret.label`,
  `e27.scr126.secret.help` (CP-1), `e27.shared.ask`, `e27.shell.grace.keys`, `e27.scr126.marker`,
  `e27.scr126.buttons`
@ row 20 ‖ Hi-fi: layout and redlin
  frame 19 after the press: both wells `readonly`, their bullets kept; Verify and save in
  CMP-001's loading state (the spinner replaces the label, width locked, `aria-busy`, focusable,
  activation suppressed; never gated); the result card opens with its status line only, "Checking
  the key with Bybit — environment, rights, withdrawal, IP allowlist, UID and clock…", and at
  about 3 s adds "This can take up to 12 s."; no staged reveal of the checks, no progress bar and
  no simulated time (D18; AD-16 at `MEMO:412`)
@ row 21 ‖ Hi-fi: layout and redlin
  the form card gives way to the result card, both wells cleared: the `h3`; the pass line "Saved.
  Key ...a7b8 is active on demo-1. Its secret can't be shown again." with the check; the check
  list all passed, demo-1's rows with Withdrawal and transfer "OFF ✓ · verified 14:02 UTC", the
  stored key's `last_verified_at` (D03-C15) — what the backend verified: the UID, the rights, the
  allowlist and the clock skew (`D02:242-250`; `14:2542`); [Done] (CMP-001 `primary`) back to
  SCR-125; the stepper shows both steps done; on a LIVE account the card adds "Storing this key
  doesn't turn live trading on — that has its own gate." (a deck string: no frame draws a LIVE
  save, `D02:486-490`)
@ row 21 ‖ Copy keys (§12)
  `e27.scr126.result.h3`, `e27.scr126.saved`, `e27.scr126.saved.live`, `e27.scr126.saved.done`;
  frame 3's check-list keys (§2.6)
@ row 22 ‖ Hi-fi: layout and redlin
  a LIVE registration, every environment line "LIVE (this deployment)", in four nested variants:
  (a) sub_002's key step, "API key for sub_002 · UID 1234569 · LIVE (this deployment)", with the
  format errors on press — key 8–128 and secret 8–256 characters (`22:16906-16907`); (b) the
  register step's UID error, 4–20 digits and nothing else (`22:16764`); (c) "This Bybit UID is
  already connected as 'sub_001'." (`14:2536`; a UID is unique per environment); (d) a sixth sub,
  "Bybit allows 5 sub-accounts on your tier (20 with Business KYC) — you've used 5.", with no
  acknowledgement control (the memo's C16, `MEMO:455`), and a parent in the other environment
  refused, naming the mismatch
@ row 23 ‖ Frame (E27-D02 §7)
  `SCR-126 / refused: withdrawal or transfer right`
@ row 23 ‖ Hi-fi: layout and redlin
  the result card's summary is CMP-027 on a `color.status.danger.subtle` band with the octagon:
  CP-5 verbatim, whose first clause is the "nothing was stored" lead, so no separate lead line:
  "Refused: this key can withdraw or transfer, and nothing was stored. It still works at Bybit:
  delete it in Bybit's dashboard, then create a key with only the trading rights CandleViewer
  allows."; the server's `detail` sits in CMP-027's details disclosure, never as exchange text
  (D12); the check list: Environment passed, "Withdrawal and transfer" failed, every later row not
  checked; both fields clear at once (CP-5; KV-I10; `D02:511-514`)
@ row 23 ‖ Copy keys (§12)
  `e27.scr126.refused.withdrawal` (CP-5, unchanged); frame 3's check-list keys
@ row 24 ‖ Hi-fi: layout and redlin
  the summary leads "Nothing was stored." then CD-3's Bybit form, "Bybit refused requests from
  203.0.113.10. In Bybit's dashboard, set this key's IP allowlist to 203.0.113.10 [Copy] and
  nothing else, then verify again.", the address and its Copy served by this refusal's `egress_ip`
  (`22:15263-15276`); every check not checked (`KeyVerificationNotRead`, `22:16981-16995`); the
  fields stay
@ row 25 ‖ Hi-fi: layout and redlin
  "Nothing was stored." then CD-3's rule form, "CandleViewer accepts this key only if its IP
  allowlist holds exactly 203.0.113.10. Set it in Bybit's dashboard [Copy], then verify again. It
  can't be set from here."; the check list passes the rows before the allowlist, fails it with the
  whitelist it read, "holds 203.0.113.10 and 198.51.100.7" (`D02:503-504`; `22:15225-15247`), and
  leaves expiry and the probe not checked; the fields stay
@ row 26 ‖ Hi-fi: layout and redlin
  seven nested variants, one per rule, each "Nothing was stored." over the check list with that
  rule's words in its failed row (frame 3): environment "This key doesn't belong to DEMO." · other
  rights "Holds a right CandleViewer doesn't allow." · trade access "Can't trade: needs Contract
  trade — Order and Position." · unified account "This account isn't a Unified Trading Account." ·
  UID "This key belongs to another Bybit UID." · expiry "This key has expired at Bybit." · probe
  "Bybit refused the signed test call."; the environment, UID and expiry variants clear both
  fields, since no fix at Bybit turns that key into a pass and a key of the other environment is
  never held (C-2.11), and the other four keep them (`D02:505-506`, `D02:514-517`)
@ row 26 ‖ Copy keys (§12)
  `e27.scr126.refused.lead`; frame 3's failed-row keys
@ row 28 ‖ Hi-fi: layout and redlin
  the check list all passed, then CMP-027 on the danger band: "The key passed its checks but could
  not be switched on. It is stored revoked here and still works at Bybit — import it again, or
  delete it in Bybit's dashboard." — never "nothing was stored" (the memo's C8, `MEMO:447`;
  `ADR9:223-230`); the fields stay for "import it again"
@ row 29 ‖ Hi-fi: layout and redlin
  frame 19 under the KEK condition: block B of §3.1 holds CMP-092's blocking row "Trading
  disabled: the credential key is unavailable." (`SYS:66`); §3's CMP-028 panel notice (BQ-9) sits
  between the PageHeader and the form card, 64 px; Verify and save is gated by
  `keys.kek_unavailable`: the lock leads its full label, label and lock in `color.text.tertiary`,
  its fill `color.surface.raised` with a `color.border.default` hairline, its `aria-describedby`
  on the notice's `id` (one notice, many pointers; 2a)
@ row 29 ‖ Copy keys (§12)
  `e27.shell.banner.kek` (consumed, `SYS:66`); the notice's first line is the reason
  `keys.kek_unavailable`; its second `e27.shared.kek_notice`
@ row 30 ‖ Hi-fi: layout and redlin
  SCR-006 over frame 19, consumed from E09-D06 and never redrawn: the board draws frame 19 under a
  flat 60 % scrim (`opacity.scrim`, no blur) with SCR-006's footprint labelled "SCR-006 code-only,
  E09-D06" (`D06:16-17`, `D06:27-28`): `role="alertdialog"`, password and code fields (`D06:47`),
  focus on the password field; its title "Confirm it's you" and its description the server's
  `action_summary` verbatim, here in `22:14996`'s form for demo-1, "Import API key for account
  'demo-1' (demo, UID 9000001)" (`22:15977-16002`); the press is held unchanged and re-sent once
  on success (`22:11910-11919`; `D06:40`); a cancel, the expiry, the third failure, the idle lock
  (SCR-005) or the absolute session expiry drops it, with "Not saved — nothing was sent." and both
  secret fields cleared (KV-I10; `22:11915-11916`); a re-send that gets no answer (a network error
  or a timeout) may have stored the key, so the card never says "Not saved" and never sends again:
  it shows `e27.shared.resend_unconfirmed`, reads the key list back (`listApiKeys`) and shows what
  it finds — the key listed, frame 21's result with both fields cleared; not listed, nothing was
  stored and the fields stay for a new Verify and save (`22:11915-11919`); inside the 5-minute
  `keys` grace no dialog opens and the ask line reads "Still trusted for key changes · 02:14"
  (`22:11921-11924`)
@ row 30 ‖ Copy keys (§12)
  `e27.scr126.stepup.dropped`, `e27.shared.resend_unconfirmed`, `e27.shell.grace.keys`; SCR-006's
  strings are E09-D06's and the server's
@ row 30 ‖ Focus and announcements
  password → code → Cancel → Confirm; `Esc` is a safe no-op (`D02:1052`); on success the result
  heading takes focus; failures assertive (`D06:67`)
@ row 31 ‖ Frame (E27-D02 §7)
  `SCR-126 / edit mode: no key field, the key row with Rotate`
@ row 31 ‖ Hi-fi: layout and redlin
  the route `/admin/accounts/:accountId` for sub_002: the `h1` "Edit sub_002 · LIVE" (new,
  PROPOSED: the title carries the environment, `D02:262-270`); the form card holds Label
  (editable) and the account's facts as CMP-036 rows (Bybit UID 1234569, sub-account of Main,
  "LIVE (this deployment)"), then the key as an outcome row: "API key ...e5f6 · active · verified
  14:02 UTC · Rotation due 2026-11-04 UTC" (sub_002's 78-day key, as frames 9, 33 and 42 date it;
  `D02:521`'s 2027-01-18 is its frame 6 fixture) with [Rotate key…] (CMP-001 `secondary`, opening
  SCR-127) and "Write-only: the secret can't be shown or changed here; a new key goes through
  Rotate."; a keyless account shows "Add a key…" in its place; Disable… and Delete (keeps
  history)… (CMP-001 `secondary`) open SCR-129; [Cancel] [Save] (new, PROPOSED) send
  `updateExchangeAccount` with `If-Match` through frame 5's rung-1 dialog (`D02:277`; §2.6), whose
  marker is "Recorded in the audit log" with no code
@ row 31 ‖ Components (variant · pr
  CMP-050 · CMP-040 + CMP-007 · CMP-036 · CMP-034 · CMP-175 `key` facets · CMP-001
@ row 31 ‖ Tokens (§9)
  rows `row-text`, `row-secondary`; the key id `type.num.base`; the write-only line
  `row-secondary`
@ row 31 ‖ Focus and announcements
  Label → Rotate key… → Disable… → Delete (keeps history)… → Cancel → Save; `Enter` in Label opens
  the rung-1 dialog
§ spec ‖ 4.4 SCR-016 step 3 — the account step as insets
@ prose
  The step is SCR-126 inline (`14:417`; `D02:864-866`): one "Verify and save" registers the shell
  and verifies and stores the key (D5); the verdict is a row the server fills after a pass, never
  a box the owner ticks (C-7; the memo's F-19, `MEMO:260`); the environment is the deployment's,
  stated in words (OQ-4).
@ head 3
  Size · tokens
@ row C Step card (CMP-050) ‖ Content and copy
  §4.1's form card at 640 px, in E27-D02 §5.7's order: Label [demo-1], Bybit UID [9000001] and
  "Main account" as text; the instruction list (§4.1 E); API key and API secret with CP-1 (§4.1
  G–H); the allowlist row with CP-3 and its stamped Copy (§4.1 F; BQ-15); [Verify and save] with
  the ask line
@ row D Result row ‖ Content and copy
  "Withdrawal and transfer: OFF ✓ — verified 14:02 UTC", a row the server fills after a pass, with
  the check list under it; before a verdict the row is absent, never OFF (AD-3)
@ prose
  **Focus (R3).** The stepper's done steps → Label → Bybit UID → API key → API secret → Copy →
  Verify and save → Back → Skip for now → Continue (`D02:854-860`); the step heading takes focus
  on each step change (`14:434`).
@ head 4
  Hi-fi: layout and redline (dark; light by token)
@ head 6
  Tokens (§9)
@ head 7
  Copy keys (§12)
@ row 72 ‖ Hi-fi: layout and redlin
  the card after the press, as SCR-126's frame 20: wells `readonly`, Verify and save loading, the
  status line and, at about 3 s, "This can take up to 12 s."; Continue stays enabled and, pressed,
  says "Verify and save the key first, or skip this step." (`D02:869-870`)
@ row 73 ‖ Copy keys (§12)
  `e27.scr016.result`; frame 3's check-list keys
@ row 74 ‖ Hi-fi: layout and redlin
  the hard block of `14:433` drawn as SCR-126's frame 23: CP-5's refusal on the danger band,
  "nothing was stored", the check list with the withdrawal row failed; both wells cleared at once
  (`D02:511-514`); Continue answers as in frame 72, and Skip for now stays
@ row 74 ‖ Copy keys (§12)
  `e27.scr126.refused.withdrawal` (CP-5, unchanged)
@ row 75 ‖ Hi-fi: layout and redlin
  the step after Skip for now: the card gives way to "Skipped — the key you add later goes through
  the same check." — a skip skips the step, never the check (the memo's IM-17, `MEMO:434`);
  Continue moves on; SCR-019's account tasks stay pending (§8)
§ spec ‖ 5. SCR-127 — Key rotation (board 07)
@ heading
  ## 5. SCR-127 — Key rotation (board 07)
@ prose
  A modal wizard, opened by "Rotate key…" from SCR-125's row menu, SCR-128's per-key menu or
  SCR-126's edit key row (`D02:421-422`, `D02:624`, `D02:520-524`).
@ prose
  It runs the contract's two-phase `rotateApiKey` (`22:2876-2950`): the new key goes through the
  `createApiKey` pipeline; on a pass the old key turns `rotating`, both keys work for the fixed
  900 s overlap while requests in flight drain, and the old key is then revoked here; no request
  changes the overlap, and a suspected compromise never rotates (`22:2885-2893`).
@ prose
  The five stages are binding (D8, `D02:194`); their form, rung 1 with the `keys` step-up
  (`D02:279`; OQ-10, `MEMO:541`; `SU:522`) and every string here are PROPOSED.
@ prose
  Board 07 draws frames 33–41 in dark; light is the same layout by token (no twin, BQ-2), and the
  light differences that matter are named per row.
@ prose
  No frame draws a rollback, an early revoke, a drain read, a `failed` state or a schedule control
  (G-4; AD-6, `MEMO:402`; `D02:582-584`), and no frame shows more of a key than its masked id
  `...{last4}` or anything of a secret (BQ-8; C-2.7, C-12.2).
@ head 3
  Size · tokens
@ row Title ‖ Content and copy
  "Rotate the key of sub_002 (...e5f6) · LIVE": the title, then CMP-075 EnvBadgeLocal for the
  environment
@ row Stage body ‖ Size · tokens
  `type.ui.body`, `color.text.primary`; secondary sentences `color.text.secondary`; UID, times,
  dates, addresses and masked ids `type.num.base`; `space.stack.sm` between paragraphs
@ row Key fields (stage 2) ‖ Block
  Key fields (stage 2)
@ row Key fields (stage 2) ‖ Content and copy
  two CMP-040 stacked fields holding CMP-201's write-only variant (§2.3, BQ-8): "New API key" with
  "value is write-only", "New API secret" with CP-1's sentence, each line in the DOM at mount
  through `aria-describedby`; `type=password`, autocomplete suppressed, paste allowed, no reveal
  control and no copy control; both cleared on Cancel, on leaving the dialog, after an
  environment, UID or expiry refusal, when a step-up is cancelled, expires or fails a third time,
  on the idle lock (SCR-005), at absolute session expiry and on sign-out (`22:11915-11916`), and
  once the server answers `200`
@ row Ask line (stage 2) ‖ Content and copy
  "You'll confirm with your password and a code."; inside the `keys` grace window "Still trusted
  for key changes · {mm:ss}", from the server's `step_up_expires_at`, never a client clock
@ row Audit marker (stage 2) ‖ Content and copy
  CMP-093's line, "Recorded in the audit log · API key rotated (api_key.rotate)", the last line
  before the footer
@ prose
  **Data and producers.** `rotateApiKey`'s `200` is an `ApiKeyRotation` (`new_key`,
  `verification`, `overlap_until`, `state: overlapping`; `22:17126-17134`) and drives stages 3 →
  4; a `422` is a refusal carrying the `verification` the pipeline reached, its `egress_ip`
  included (frame 36; `22:2745-2749`); a `503` is no verdict (frame 37); stage 5 reads the old
  key's `revoked` from `GET /exchange-accounts/{accountId}/keys` (`D02:559-561`).
@ prose
  The route is `keys:manage`, the Owner's alone, and not mounted at the base (`MX:596-602`).
@ prose
  Events: `api_key.rotate` once the switch happens (`ACT:137`), `security.key_policy_violation` on
  a refused new key, nothing for the instructions or a no-verdict answer (`D02:954-962`).
@ prose
  `Enter` acts on Next and on Verify and switch; `Space` toggles the stage-5 note (`D02:1067`);
  `Enter` in a key field never presses Verify and switch (PROPOSED: a rung's confirm is pressed on
  itself, as E42-D03:594 rules for its typed fields).
@ prose
  CMP-035: `overlap_until` is the primary, absolute time and the relative mm:ss the secondary; it
  is text, `type.num.*` replacing `font.mono` (not a token, `15:386`); no warning colour
  (`color.text.warning` is not a token either) and no "secret auto-hide" use (BQ-8); the list rows
  never tick — they show only the absolute line (`D02:578`).
@ head 4
  Hi-fi (dark; light by token)
@ head 5
  Tokens
@ head 6
  Copy keys
@ row 33 ‖ Frame (E27-D02 §7)
  `SCR-127 / stage 1: create the new key at Bybit`
@ row 33 ‖ Hi-fi (dark; light by to
  Stepper: 1 current, 2–5 not started. `h2` "Create the new key at Bybit". An ordered list: "In
  Bybit's dashboard, create a new key for UID 1234569 with only Contract trade — Order and
  Position, and no withdrawal or transfer right." · CP-3, "Set this key's IP allowlist in Bybit's
  dashboard to exactly 203.0.113.10 [Copy]. It can't be set here; CandleViewer only checks it." —
  the address and its CMP-033 Copy drawn as a target state stamped "not yet served — D03-G1,
  #896": no read serves the address before a check (BQ-15 item 7; `22:16969-16980`) · the key-age
  policy, "Keys are due for rotation every 90 days; this one is 78 days old (due 2026-11-04 UTC).
  Overdue never stops trading." · the 48 h line, "Rotating doesn't start Bybit's 48 h wait: that
  applies to a new account's first key.", stamped PROPOSED (OQ-5; RA-7, `MEMO:280`). No ask line
  and no marker: nothing is sent at this stage. Footer [Cancel] [Next]; no Back. Focus: the `h2`;
  Tab Copy → Cancel → Next.
@ row 34 ‖ Hi-fi (dark; light by to
  Stepper: 1 done, 2 current. `h2` "Paste the new key". Before the fields, the consequences of the
  press: RA-1's lead, "Open orders stay open. Both keys work for 15 minutes while requests
  drain.", and "Then the old key ...e5f6 is revoked here. There is no undo: to go back, rotate
  again." (PROPOSED: OQ-10's line, `D02:577`, moved before the confirm so the rung states what it
  cannot undo first). The two write-only fields, the ask line, the marker; footer [Cancel] [Back]
  [Verify and switch] — the destructive confirm, rung 1, enabled at once; an empty field shows its
  inline error on the press (`D02:1033-1035`). Without a live grace the press opens SCR-006 over
  the wizard (T1; E09-D06's chassis, consumed and never redrawn; password and code; its
  description the server's `action_summary` verbatim, which names sub_002 with LIVE and UID
  1234569, `22:11857-11863`); the held request is re-sent once on success; Cancel, expiry, a third
  failure, the idle lock (SCR-005) or the absolute session expiry reads "Not saved — nothing was
  sent." and clears both fields (`D02:530-531`; `22:11915-11916`); a re-send that gets no answer
  may have rotated the key, so the wizard never says "Not saved" and never sends again: it shows
  `e27.shared.resend_unconfirmed`, reads the key list back (`listApiKeys`) and shows what it finds
  — the old key `rotating`, the switch happened (stage 4), or still `active`, nothing changed
  (stage 2) (`22:11915-11919`). Board 07 draws stage 2 and, inset, SCR-006 over it. Focus: the
  `h2`; Tab New API key → New API secret → Cancel → Back → Verify and switch.
@ row 34 ‖ Copy keys
  `e27.scr127.stage2.h2` · `e27.scr127.stage2.lead` · `e27.scr127.stage2.no_undo` ·
  `e27.scr127.stage2.fields` · `e27.scr126.key.label` · `e27.scr127.secret.help` ·
  `e27.shared.ask` · `e27.shell.grace.keys` · `e27.scr127.marker` · `e27.scr127.buttons` ·
  `e27.scr126.stepup.dropped` · `e27.shared.resend_unconfirmed`
@ row 35 ‖ Hi-fi (dark; light by to
  Stepper: 1–2 done, 3 current with its running `meta`, "Verify · 2 s". `h2` "Verifying the new
  key". D18's line, "Checking the key with Bybit — environment, rights, withdrawal, IP allowlist,
  UID and clock…", and after about 3 s "This can take up to 12 s." (H8, `MEMO:196`). The fields
  stay, read-only and masked. Verify and switch is busy: CMP-001 `loading`, its label kept,
  `aria-busy="true"`, focusable, no lock, never T2. Back is gone and Cancel becomes [Close]: the
  request is in flight and closing changes nothing (PROPOSED, from `D02:588-589`). The checks
  never appear one by one and nothing fakes progress: they arrive with the answer (D18; BQ-12's
  rider to E27-D04). Focus: the `h2` (the press moved it).
@ row 36 ‖ Frame (E27-D02 §7)
  `SCR-127 / stage 3 refused: nothing changed, the old key still active`
@ row 36 ‖ Hi-fi (dark; light by to
  Stepper: 3 in its error status, the octagon and "Refused — nothing changed". `h2` "The new key
  was refused". Under it the CMP-027 summary (`role="alert"`, assertive once): "Nothing changed —
  the old key ...e5f6 is still active." (RA-6, `MEMO:279`). Then the CMP-203 check list in its
  three outcomes (BQ-14) for sub_002's new key: Environment "passed — this key belongs to LIVE" ·
  Withdrawal and transfer "OFF ✓ · verified 10:39 UTC" (the check's time, D03-C15) · Other rights
  "only Contract trade: Order, Position" · Trade access "passed — a trade key" · Unified account
  "passed" · UID "passed — UID 1234569" · IP allowlist failed, CD-3's rule form, "CandleViewer
  accepts this key only if its IP allowlist holds exactly 203.0.113.10. Set it in Bybit's
  dashboard [Copy], then verify again. It can't be set from here." with the whitelist read "holds
  203.0.113.10 and 198.51.100.7" — the address is served in the `422`'s `verification`, so this
  Copy is live (`22:2745-2749`) · Expiry "passed — none set" · Signed probe and clock "passed —
  clock offset 4 ms" (`D02:240-258`). Then "The new key still works at Bybit; delete it there if
  you won't use it." Footer [Cancel] [Back to paste]; the fields keep their masked values for the
  resend (an allowlist refusal never clears them, `D02:511-518`). Focus: the `h2`.
@ row 36 ‖ Copy keys
  `e27.scr127.stepper.status` · `e27.scr127.stage3.refused_h2` · `e27.scr127.stage3.refused` ·
  `e27.scr127.stage3.new_key_lives` · `e27.scr127.stage3.back` · the check list's keys (§2.6,
  frame 3)
@ row 37 ‖ Hi-fi (dark; light by to
  Stepper: 3 stays current (nothing was judged, so no error status). `h2` "No answer from Bybit".
  CMP-027 (`role="alert"`, once): "No answer from Bybit — nothing changed; the old key is still
  active. Try again in 5 s." — the 5 s is the server's `Retry-After`, written once, never a
  ticking count. No check list: no check reached a verdict (`D02:574`; `22:2753-2764`). Footer
  [Cancel] [Back to paste]: trying again is stage 2's Verify and switch, with the consequences
  read again before the press; the masked values stay. Focus: the `h2`.
@ row 38 ‖ Hi-fi (dark; light by to
  Stepper: 1–3 done (3 with "Verify · 2.4 s"), 4 current. The `200` cleared both write-only fields
  (CMP-201's clear after a successful save, §2.3), as frame 21 clears SCR-126's. `h2` "Switched".
  "Switched at 10:40:01 UTC. New requests use ...d9e0. The old key ...e5f6 keeps working here
  until 10:55:01 UTC — {mm:ss} left — while requests in flight finish. Open orders stay open."
  with CMP-035 in place of its two times (absolute first, relative second), then "There is no
  undo: to go back, rotate again." (OQ-10). The switch time is `overlap_until` less the fixed 900
  s, both served (`22:2885-2890`); the private WebSocket re-authenticates with ...d9e0 at the
  switch, with no UI (`22:2891-2892`). Footer [Close] only: closing leaves the overlap running,
  and the rows then show "Rotation in progress · old key usable until 10:55:01 UTC" (busy, not T2;
  `D02:578`, `D02:1028-1029`). The stage advances to 5 only on the server's state. Announcements,
  polite: "1 minute left on the old key ...e5f6, until 10:55:01 UTC." at 60 s and "10 seconds left
  on the old key ...e5f6, until 10:55:01 UTC." at 10 s; nothing per tick. Event `api_key.rotate`
  (`ACT:137`). Focus: the `h2` (the answer to the press moved it).
@ row 39 ‖ Frame (E27-D02 §7)
  `SCR-127 / stage 5: old key revoked here, delete it at Bybit`
@ row 39 ‖ Hi-fi (dark; light by to
  Stepper: all five done. `h2` "Old key revoked here". CP-4 and CD-8 together: "Revoked in
  CandleViewer. The key still works at Bybit until you delete it in Bybit's dashboard." Then the
  CMP-005 note, unchecked at mount: "I deleted ...e5f6 in Bybit's dashboard — a note for you; it
  unlocks nothing and records nothing" — never required, never styled as a step to complete,
  gating and recording nothing (`MEMO:296`; BQ-15 item 6's one string). Footer [Close] (primary).
  Its arrival is the countdown's end, announced politely once with CP-4's sentence above (§11). If
  the wizard is open, focus moves to the `h2`; Tab the note → Close.
@ row 40 ‖ Hi-fi (dark; light by to
  Frame 38's stage 4 exactly, plus the board's annotation strip — never product UI, never a story:
  "not yet served — G-4, #897: no read of the requests still in flight, no rollback before the old
  key is revoked, no early revoke of the old key, `state: failed` undefined (`22:17134`); no
  schedule control (`D02:582-584`)". No control, link or disabled button stands in for any of
  them, and nothing on the frame is T2 (D20, `D02:206`).
@ row 40 ‖ Tokens
  the anatomy's; the strip is a board annotation, not a token binding
@ row 41 ‖ Hi-fi (dark; light by to
  SCR-125 under the system banner — CMP-092's blocking row with the server's "Trading disabled:
  the credential key is unavailable." (`SYS:66`) — and the one CMP-028 notice under the `h1`
  (BQ-9), with sub_002's row menu open (CMP-041, "Actions for sub_002 · LIVE"): "Rotate key…"
  keeps its place, its role and its full label, the CMP-019 `lock` ("Not available") leading it,
  `aria-disabled="true"`, its second line "Off while the credential key is unavailable."
  (`keys.kek_unavailable`, 2a; CMP-079 once the E27 keys are registered, the item's own
  `disabledReason` until then, E42-D03:602) and its `aria-describedby` naming that line and the
  notice (one notice, many pointers). The wizard never opens. "Add a key…" and "Test key…" carry
  the same reason; "Revoke key…", "Suspected compromise…", "Disable…" and "Delete (keeps
  history)…" stay enabled (D17, `D02:203`). `Enter` or `Space` on the item changes nothing,
  re-shows the reason with one polite announcement and sends nothing; the item emits nothing.
@ row 41 ‖ Copy keys
  `keys.kek_unavailable` · the row menu's item keys (§3) · the KEK notice's keys (one string set
  for every screen's notice, §12.1)
§ spec ‖ 6. SCR-128 — Key health and secrets policy (boar
@ heading
  ## 6. SCR-128 — Key health and secrets policy (boards 04 and 05)
@ prose
  A panel of `/admin/accounts` under SCR-125's list, never a route of its own: a CMP-051
  disclosure whose header is the `h2`'s button "Key health and secrets policy" (`aria-expanded`),
  collapsed by default, its open state kept in the URL so a strip item can deep-link to it
  (`D02:622-625`).
@ prose
  It holds the rate line, the per-key table, the Test sentence and the secrets-at-rest policy in
  sentences; "Suspected compromise…" opens the ordered card first under the `h1` (`D02:640-645`).
@ prose
  Owner only (`audit:read`, `keys:read`; everyone else meets SCR-155, T3); comfortable density on
  the screen (BQ-4).
@ prose
  The table's rights and allowlist cells are CMP-175's E27 state set (§2.1), which E43-D02 extends
  additively and never forks (BQ-5).
@ head 3
  Size · tokens
@ row Disclosure ‖ Content and copy
  the `h2`'s button "Key health and secrets policy" with a chevron, `aria-expanded` and
  `aria-controls`; collapsed by default; opening it fires `admin.key_health_viewed` (analytics)
@ row Key table ‖ Block
  Key table
@ row Key table ‖ Content and copy
  CMP-049 in its table form — a plain `<table>`, no grid, no sort, no paging — with the visible
  caption "Stored API keys, grouped LIVE then DEMO" (`type.ui.label`, `color.text.secondary`); two
  row groups, "LIVE (3)" and "DEMO (1)", each a `th scope="rowgroup"` with CMP-075's badge; one
  row per signable key, the account cell `th scope="row"`; the columns below
@ row Test sentence ‖ Content and copy
  under the table: "Test runs the full check: if a key fails it, trading stops on every account
  until a restart passes the check, and trading on its account stays off until you turn it back
  on." (CP-6 in panel form); "Overdue never stops trading." follows it whenever a key is overdue
@ row Policy ‖ Content and copy
  `h3` "How CandleViewer holds your keys", then a list of the seven sentences of `D02:607-619`,
  always shown while the panel is open
@ row Row menu ‖ Content and copy
  CMP-041 behind "Actions for ...a1b2": "Test key…" · "Rotate key…", whose second line says the
  ask before the press ("Asks for your password and a code" or the grace line) · "Suspected
  compromise…"; Test and Suspected compromise ask nothing before the press
@ row Key ‖ Column
  Key
@ row Key ‖ Cell
  CMP-034, the masked id `...{last4}` and nothing more (BQ-8; `22:16879-16882`); `type.num.base`
@ row Status ‖ Cell
  the key's `status` as a word: active · rotating · invalid · expired at Bybit (`KeyStatus`,
  `22:16092-16099`; "expired" names only Bybit's own expiry, AD-5)
@ row Rights ‖ Cell
  CMP-175 in its `key` scope: the trade facet and the dated withdrawal facet in §2.1's words,
  "Trade · Withdrawal OFF ✓ · verified 14:02 UTC", where D02 draws "Trade, Withdrawal OFF ✓" with
  no time (`D02:599`; D03-C15) — two text lines in this column, breaking before "verified"; a fund
  right is the critical "BLOCKED — fund right found" and routes to the compromise card, never to
  Rotate (`keys.compromise_path`, `D02:316`)
@ row Allowlist ‖ Cell
  CMP-175's allowlist facet in its header form (§2.1): "matches" (check) · "no match" or "none
  set" (octagon) · "not checked" (dash), never "n/a" and never a warning
@ prose
  At 1280 × 800 the Rights cell's dated word already takes two lines, so a key row is about 44 px
  (`min-height`).
@ prose
  At 200 % the rows reflow to one card per key, the account and key first, then the facts as
  label–value pairs, Actions after the key (SCR-125's reflow, `D02:1087-1088`).
@ prose
  **Data and producers (Owner only).** The table: `GET /admin/security/summary`
  (`getSecuritySummary`, `audit:read`; per key `status`, `age_days`, `expires_at`,
  `withdrawal_permission_present`, `ip_whitelist_matches_expected`, `last_verified_at`;
  `22:13742-13754`, `22:22011-22033`; not mounted, `MX:202-208`) and the key list, `GET
  /exchange-accounts/{accountId}/keys` (`rotation_due_at`, `rotation_state`; `22:16873-16900`),
  computed server-side and cached 60 s, never an exchange call from the browser (`14:2565`).
@ prose
  The KEK notice: the `system` notice `secrets.kek_unavailable` (`23:4262`) and the server's
  banner sentence (`SYS:66`).
@ prose
  The card: step 1 is E39's freeze (`POST /trading/kill-switch`; not mounted, `MX:1521-1527`),
  step 3 `revokeApiKey` through §7's revoke dialog, step 5 SCR-126's key step (`createApiKey`);
  `admin.key_marked_compromised` has no operation and no registered code (G-6; `TM:612`), so the
  card writes nothing of its own (`D02:666-671`).
@ prose
  Opening the card moves focus to its `h2` (the press moved it); inside it Tab runs Freeze → the
  note → Revoke here → Add a new key → Close card, and each step's control opens its own dialog
  and returns focus to that control (`D02:686-690`); the steps never time out (A-O).
@ head 4
  Hi-fi (dark; light by token)
@ head 5
  Tokens
@ head 6
  Copy keys
@ row 42 ‖ Frame (E27-D02 §7)
  `SCR-128 / key table and the secrets-at-rest policy`
@ row 42 ‖ Hi-fi (dark; light by to
  The panel open under SCR-125 (the anatomy): the rate line; the table with four rows in two
  groups — LIVE: Main ...a1b2 active 41 d 2026-12-11 UTC · sub_001 ...c3d4 active 12 d 2027-01-09
  UTC · sub_002 ...e5f6 active 78 d 2026-11-04 UTC with the warning chip "Rotation due in 12 d"
  (triangle); DEMO: demo-1 ...a7b8 active 30 d 2026-12-22 UTC (`D02:597-603`). Every Rights cell
  shows the pass facets with their time and every Allowlist cell "matches", each an affirmative,
  dated word, never the absence of a warning (CMP-175, §2.1; AD-3, `MEMO:399`). Then the Test
  sentence and the policy: its seven sentences as `D02:607-619` words them, the fourth, "IP
  allowlists are set in Bybit's dashboard only; each key must allow exactly 203.0.113.10.
  CandleViewer only checks it.", with the address a target state stamped "not yet served — D03-G1,
  #896" (BQ-15 item 7). No key material, fingerprint, ciphertext or KEK id anywhere (C-12.2;
  BQ-1). Focus: the disclosure; then the rows' Actions buttons in row order.
@ row 42 ‖ Copy keys
  `e27.shell.region.health` · `e27.scr128.rate_budget` · `e27.scr128.table.caption` ·
  `e27.scr128.table.headers` · `e27.scr125.group` · `e27.scr128.status` · `e27.scr128.row.actions`
  · `e27.scr128.test_note` · `e27.scr128.policy.h3` · `e27.scr128.policy.encrypted` ·
  `e27.scr128.policy.write_only` · `e27.scr128.policy.backups` · `e27.scr128.policy.allowlist` ·
  `e27.scr128.policy.withdrawal` · `e27.scr128.policy.rotation` · `e27.scr128.policy.kek` · the
  CMP-175 and CMP-011 words (§2.1, §3)
@ row 43 ‖ Hi-fi (dark; light by to
  Frame 42 once 2026-11-04 UTC has passed: sub_002's Rotation due cell shows "2026-11-04 UTC" over
  CMP-011's warning chip with the clock, "Rotation overdue"; the cell's accessible text is
  "Rotation overdue since 2026-11-04 UTC" (`D02:633-634`). No octagon and no danger tone anywhere
  on the row: overdue is a warning, never an error, and age alone never disables a key
  (`22:16899-16900`). "Overdue never stops trading." follows the Test sentence; the shell's strip
  carries "Rotation overdue for sub_002 → Rotate" (CMP-087's strip; `D02:635`); the row's menu
  keeps "Rotate key…" as it was.
@ row 44 ‖ Hi-fi (dark; light by to
  The Test dialog (CMP-043 `role="dialog"`, SCR-125's dialog of §3) over the panel for Main's key:
  title "Test Main's key ...a1b2 · LIVE"; its result — the CMP-203 check list all passed,
  Environment "passed — this key belongs to LIVE" and UID "passed — UID 1234567" (`D02:252-258`),
  then "REST probe: passed · 118 ms" and "WebSocket: not checked" (diagnostic only); under them
  CP-6's pass sentence, "Passed — trading stays read-only until a restart passes the check. If a
  failed check turned this account's trading off, it stays off until you turn it back on.";
  [Close]. Behind it the system banner stays ("Trading disabled: a stored API key failed its
  check.", `SYS:71`), and Main's SCR-125 row keeps CMP-176's off-by-policy form (§2.2, BQ-7),
  "Trading on this account: off by policy", with no control, stamped "not yet served — G-12,
  #3657" on the annotation layer (`D02:636-638`). The pass is announced politely once; nothing on
  the frame says trading resumed (AD-1). Focus: the result's heading (the press moved it).
@ row 44 ‖ Copy keys
  `e27.scr128.off_by_policy` · the Test dialog's keys (§3)
@ row 45 ‖ Hi-fi (dark; light by to
  Under the system banner (CMP-092's blocking row; `SYS:66`) the panel shows the CMP-028 KEK
  notice once, first in its body, as SCR-125 shows its own under the `h1` (frame 17) — one notice
  per screen (D17; BQ-9): the octagon, "Off while the credential key is unavailable." and "Keys
  can't be added, tested or rotated until the KEK is back, and trading is off." — blocking, never
  dismissible, announcing nothing itself (CMP-092's row is the one announcement). Every key's menu
  keeps "Test key…" and "Rotate key…" in place, T2 per §10.1: the `lock` leading the full label,
  `aria-disabled="true"`, the second line "Off while the credential key is unavailable."
  (`keys.kek_unavailable`, 2a; CMP-079 as in frame 41) and `aria-describedby` naming the notice
  too (one notice, many pointers). "Suspected compromise…" stays enabled, and so does its card's
  "Revoke here…" (D17, `D02:203`). The table, the policy and the Test sentence stay readable at
  full contrast.
@ row 45 ‖ Copy keys
  `keys.kek_unavailable` · the KEK notice's keys (§12.1, as frame 41) · the row menu's item keys
  (§3)
@ row 46 ‖ Hi-fi (dark; light by to
  sub_001's response open: the card first under the `h1` (the page's "Suspected compromise"
  region, `D02:153-155`), its `h2` "Suspected compromise · sub_001 · key ...c3d4 · LIVE" with
  [Close card]; the lead "Do these in order. CandleViewer can stop its own trading on sub_001 and
  end the key here; only you can kill the key at Bybit."; the five steps in C-12.12's order
  (binding, D9; `CON:824-825`): 1 "Freeze sub_001 — new orders stop here at once. No code. If you
  also cancel or flatten there, don't wait for it." [Freeze sub_001…] (E39's rung-0 dialog,
  consumed) · 2 "Delete key ...c3d4 in Bybit's dashboard now. Don't wait for step 3 or for a
  flatten: this is the only step that stops the key, and CandleViewer can't do it or confirm it."
  with the CMP-005 note "I deleted ...c3d4 in Bybit's dashboard — a note for you; it unlocks
  nothing and records nothing" (BQ-15 item 6: stage 5's string, refined from `D02:654`) · 3
  "Revoke it here — ends the key in CandleViewer." [Revoke here…] (§7's revoke dialog) and "If the
  revoke is refused, step 2 is still the one that counts." · 4 "Rotate the credential key (KEK),
  sign every session out and audit every order in the exposure window. The compromise runbook does
  these; there is no control here." · 5 "Replace the key — only after step 4." [Add a new key…]
  (SCR-126's key step); then "Then release the freeze and re-arm the rules by hand." and the
  marker "Recorded: the freeze, the revoke and the new key each in the audit log. Marking a
  compromise has no record of its own yet." (`D02:647-662`). No Rotate anywhere on the card, no
  flatten-first before the Bybit delete (OQ-16, `D02:671-675`), and no step is a wait or times
  out. Focus: the `h2`; Tab per the keyboard paragraph.
@ row 47 ‖ Hi-fi (dark; light by to
  The card after "Revoke here…" was refused: step 3's line becomes the CMP-027 inline error
  (`role="alert"`, assertive once) "Not revoked: BTCUSDT long 0.250 has no stop-loss, so leaving
  positions is refused." — or "Not revoked: the account is not flat.", or frame 56's fixable
  remedy for sub_001 (`D02:679-680`) — followed at once by "Delete the key at Bybit now (step 2) —
  that stops it."; no other next step is offered first (AD-7, `MEMO:403`). Step 2 keeps its note;
  "Revoke here…" stays enabled for a retry, and focus returns to it when the revoke dialog closes.
@ row 48 ‖ Hi-fi (dark; light by to
  After the owner deleted ...c3d4 at Bybit, step 3 reads "Bybit no longer accepts key ...c3d4, so
  sub_001 can't be read or flattened here. Revoking leaves its 2 positions at Bybit, each with
  whatever stop-loss it carries — check each in Bybit's dashboard." and "Trading is read-only for
  every account until the key is revoked here and a restart passes the check — that is the
  containment C-12.12 asks for." (`D02:682-685`; `22:14531-14544`; `RB:30-31`): the read-only
  state is stated as containment, never as a cost. "Revoke here…" opens §7's revoke dialog with
  leaving the positions as its only choice — the dead remedy (`22:14531-14544`) — and the confirm
  "Revoke here and leave positions open". The note stays as the owner left it: it gates nothing.
  Event, once revoked: `api_key.revoke` carrying `exposure_unknown` (`22:14539-14544`).
§ spec ‖ 7. SCR-129 — Disable, delete and the revoke dial
@ prose
  Comfortable density; board 08 draws frames 49–61 in dark, light by token.
@ head 3
  Size · tokens
@ row Title ‖ Content and copy
  "Revoke key ...e5f6 on sub_002 · LIVE" · "Disable sub_002 · LIVE" · "Delete sub_002 (keeps
  history) · LIVE", the environment as CMP-075's badge
@ row Ask line ‖ Content and copy
  revoke: "You'll confirm with your password and a code." (the `keys` class, served), or inside
  the grace "Still trusted for key changes · {mm:ss}"; disable and delete: the same sentence as a
  target state stamped "not yet served — G-8, #895 / #898" (no class serves them yet)
@ row Marker ‖ Content and copy
  revoke: "Recorded in the audit log · API key revoked (api_key.revoke)"; disable and delete:
  "Recorded in the audit log", with no code (none registered)
@ prose
  **The confirms: the consequence before the press, the step-up, the token** (Enable… alone is not
  destructive).
@ head 2
  Rung · typed token
@ row Revoke a key that is not the last (49) ‖ Action (frames)
  Revoke a key that is not the last (49)
@ row Revoke a key that is not the last (49) ‖ Step-up
  `keys`, served (`SU:523`)
@ row Revoke a key that is not the last (49) ‖ Confirm label
  "Revoke key ...e5f6 here" (new)
@ row Revoke the last active key, with exposur ‖ Action (frames)
  Revoke the last active key, with exposure (50, 51)
@ row Revoke the last active key, with exposur ‖ Consequence stated befor
  "sub_002 has no other active key: it stops trading here.", the counts with each position's
  stop-loss state, CP-4's Bybit clause, CD-6's two choices
@ row Revoke the last active key, with exposur ‖ Step-up
  `keys`, served
@ row Revoke the last key of a dead account (4 ‖ Action (frames)
  Revoke the last key of a dead account (48's card, 56's remedy)
@ row Revoke the last key of a dead account (4 ‖ Step-up
  `keys`, served
@ prose
  **Data and producers.** Disable is `updateExchangeAccount` with `enabled: false`
  (`accounts:write`; `22:2592-2631`, the disable rule at `22:2601-2606`); delete is
  `deleteExchangeAccount`, `flatten_first` its only choice (`22:2632-2669`); revoke is
  `revokeApiKey` (`keys:manage`; `22:2838-2875`; not mounted, `MX:589-595`), local only — the key
  stays valid at Bybit until the Owner deletes it there (`22:2847-2852`).
@ head 4
  Hi-fi (dark; light by token)
@ head 5
  Tokens
@ head 6
  Copy keys
@ row 49 ‖ Frame (E27-D02 §7)
  `SCR-129 / revoke a key that is not the last: rung 1`
@ row 49 ‖ Hi-fi (dark; light by to
  Opened from "Revoke key…" on sub_002's row while ...d9e0 is also active: title "Revoke key
  ...e5f6 on sub_002 · LIVE"; the consequence, "It stops working here at once; sub_002 keeps
  trading on ...d9e0. It still works at Bybit until you delete it in Bybit's dashboard." — CP-4's
  two clauses together, as H6 asks (`MEMO:194`); no choices, because another active key remains
  and the account keeps trading (`22:2854-2860`); no typed label (rung 1); the ask line (served)
  and the marker; [Cancel] [Revoke key ...e5f6 here], the confirm rendered and enabled at once.
  Without a live grace the press opens SCR-006 (T1), the request held and re-sent once
  (`22:11851-11863`); a re-send that gets no answer may have revoked the key, so the dialog never
  says it was not sent and never sends again: it shows `e27.shared.resend_unconfirmed`, reads the
  key list back (`listApiKeys`) and shows frame 52's outcome on a `revoked` key, or the key still
  active (`22:11915-11919`). Focus: Cancel; `Esc` cancels; focus returns to "Actions for sub_002 ·
  LIVE".
@ row 50 ‖ Frame (E27-D02 §7)
  `SCR-129 / revoke the last key with exposure: two choices, none selected`
@ row 50 ‖ Hi-fi (dark; light by to
  ...e5f6 is sub_002's only active key and the account holds exposure: title as frame 49; the
  list: "sub_002 has no other active key: it stops trading here." · "sub_002 holds 2 positions, 3
  working orders and 1 running algo." · "BTCUSDT long 0.250 — has its stop-loss" · "ETHUSDT short
  1.20 — has its stop-loss" · "The key still works at Bybit until you delete it in Bybit's
  dashboard." (CP-4's second clause); CD-6's two radios, none checked: ( ) "Leave positions and
  orders open — they stay at Bybit, each position with its stop-loss; this account's algos stop
  and its rules are disarmed." ( ) "Flatten first — cancel 3 orders, stop 1 algo and close 2
  positions, then revoke." (`D02:756-757`; `MEMO:381`); "Type sub_002 to confirm:"; the ask line
  (served); the marker; [Cancel] [Choose what happens to the open positions] in the validity look
  with the hint "Choose an option first." — after a choice its label becomes "Revoke here and
  leave positions open" or "Flatten first, then revoke here", with the hint "Type sub_002 to
  confirm." until the label matches. Focus: Cancel.
@ row 51 ‖ Hi-fi (dark; light by to
  As frame 50, but the summary shows BTCUSDT long 0.250 with `native_stop_present: false`: its
  line leads with the octagon, "BTCUSDT long 0.250 — no stop-loss", and the list adds "BTCUSDT
  long 0.250 has no stop-loss; once the key is gone nothing could add one. Add its stop first, or
  choose Flatten first." "Leave positions and orders open" keeps its place, its role and its full
  label, T2 per §10.1: the `lock` leads it, `aria-disabled="true"`, its second line "Refused while
  a position has no stop-loss." (`accounts.stop_missing`, 2a; carried by CMP-044's
  `choices[].disabledReason`, CMP-079 once the key is registered, E42-D03:903); an arrow onto it
  focuses it without checking it, `Space` re-shows the reason with one polite announcement, and it
  emits nothing; "Flatten first — …" stays available, and the T2 choice can never enable the
  confirm. A `409 open_exposure` after a stale read shows the same refusal at the point of action
  (T4; `22:14505-14509`; #2903). The disable dialog's choice takes the same T2 (`D02:761-762`).
@ row 52 ‖ Hi-fi (dark; light by to
  The dialog closes and focus returns to "Actions for sub_002 · LIVE". In sub_002's row details
  (§3) the revoked key's line reads "Revoked at 14:12 UTC — delete it at Bybit" (an outcome, never
  T2; `D02:1030`), with CP-4 and CD-8 beside it, "Revoked in CandleViewer. The key still works at
  Bybit until you delete it in Bybit's dashboard." — the two clauses always together, H6's
  predicted misread placed at the action (`MEMO:194`); the shell announcer reads the outcome
  politely once. Subscribers of sub_002 read the server's "The account's API key was revoked."
  (`REV:108`).
@ row 54 ‖ Hi-fi (dark; light by to
  sub_002 holds no exposure: title "Disable sub_002 · LIVE"; the list: "sub_002 stops trading
  here; new orders on it are refused." · "Assigned users: alex (trade), bea (read) — they can no
  longer trade or open sub_002 here." · "Rules disarmed: "BTC breakout", "ETH fade"." · "History
  stays." · "You can enable it again." · "Its keys still work at Bybit." (`D02:730-732`; what else
  grant holders keep is O-F, `D02:1216`); "Type sub_002 to confirm:"; the ask line as a target
  state stamped "not yet served — G-8, #895 / #898"; "Recorded in the audit log"; [Cancel]
  [Disable sub_002] in the validity look with "Type sub_002 to confirm." until the label matches.
  No choice block: nothing is open. Focus: Cancel.
@ row 56 ‖ Hi-fi (dark; light by to
  Two forms after the press (`22:14517-14561`; `22:16839-16854`). **Dead** (`remedy:
  leave_positions`): the CMP-027 summary (`role="alert"`, once) "sub_002's keys no longer work at
  Bybit, so its positions and orders can't be read or flattened. It can be disabled, leaving them
  at Bybit, each with whatever stop-loss it carries — check each in Bybit's dashboard. It can't be
  deleted."; the dialog then offers only that resend, a new request the Owner presses — the client
  never sends it on its own (`22:16843-16853`): from Disable and from Delete the typed label, the
  stamped ask and [Cancel] [Disable and leave positions open] (a dead account is disabled, never
  deleted); from the revoke dialog, "Revoke here and leave positions open" with its served ask.
  **Fixable** (`remedy: fix_key`): "Bybit refuses sub_002's key from 203.0.113.10. Fix it in
  Bybit's dashboard [Copy], then try again; until then nothing can be revoked, disabled or
  deleted." — the address and its Copy a target state stamped "not yet served — D03-G1, #896" (the
  `409` carries no address, `22:15180-15188`); [Close] only: the action is reopened, and its
  summary read again, once the key is fixed. Focus moves to the summary (`tabindex="-1"`), since
  the answer replaces the dialog's content.
@ row 58 ‖ Hi-fi (dark; light by to
  Title "Delete sub_002 (keeps history) · LIVE"; CD-5's five sentences in CD-5's order, split as
  D02's frame splits them, the first without counts and its "Its" as "sub_002's" (`D02:744-746`):
  "Delete sub_002 (keeps history): if it holds positions, orders or running algos, it is flattened
  first — orders cancelled, algos stopped, positions closed — and deleted only once it is flat." ·
  "sub_002's keys are revoked here and it stops trading." · "Assigned users: alex (trade), bea
  (read) — they lose sub_002." · "Rules disarmed: "BTC breakout", "ETH fade"." · "Its order
  history, fills and audit log stay. This can't be undone, though the same Bybit account can be
  added again as a new one." · "Its keys still work at Bybit until you delete them there. Backups
  hold them only encrypted; without the KEK you keep offline they sign nothing." (CP-2 at the
  delete, H6's other predicted misread); "Type sub_002 to confirm:"; the stamped ask; "Recorded in
  the audit log"; [Cancel] [Delete sub_002]. No "irreversible", "permanently" or "all data
  deleted" (D11; AD-9). Focus: Cancel.
@ row 58 ‖ Copy keys
  `e27.scr129.delete.title` · `e27.scr129.delete.flat` · `e27.scr129.delete.keys` ·
  `e27.scr129.delete.users` · `e27.scr129.disable.rules` · `e27.scr129.delete.history` ·
  `e27.scr129.delete.bybit` · `e27.scr129.delete.confirm` · `e27.scr129.typed` · `e27.shared.ask`
  · `e27.scr129.marker`
@ row 60 ‖ Frame (E27-D02 §7)
  `SCR-129 / delete on an account that never had a key: T2`
@ row 60 ‖ Hi-fi (dark; light by to
  sub_002 registered with an empty key list (frame 10's state): its row menu (CMP-041, "Actions
  for sub_002 · LIVE") keeps "Delete (keeps history)…" in place, T2 per §10.1: the `lock` leading
  its full label, `aria-disabled="true"`, its second line "An account that never had a key can
  only be disabled." (`accounts.never_keyed`, 2a; CMP-079 as in frame 41) — nothing can show it
  holds no exposure (`22:14522-14524`); "Disable…" stays enabled with its ask line. `Enter` or
  `Space` on the T2 item changes nothing, opens no dialog, re-shows the reason with one polite
  announcement and emits nothing.
@ row 60 ‖ Copy keys
  `accounts.never_keyed` · the menu's item keys (§3)
@ row 61 ‖ Hi-fi (dark; light by to
  Disabled: sub_002's SCR-125 row reads "Disabled at 14:12 UTC — doesn't trade here." with
  [Enable…] in the place of "Disable…" (an outcome, never T2; #960 Q13; `D02:750-751`), at full
  text contrast and never dimmed (BQ-7; C-10, `D02:1205`). [Enable…] opens a rung-1 CMP-044 dialog
  that is not destructive: "Enable sub_002 · LIVE", its one consequence "Its rules stay disarmed
  until you arm them by hand.", the ask line as a target state stamped "not yet served — G-8, #895
  / #898", the marker "Recorded in the audit log" with no code (`24:4854` names `account.disabled`
  and no enable), then [Cancel] [Enable sub_002], the confirm a CMP-001 primary; it sends
  `updateExchangeAccount` with `enabled: true` (`accounts:write`; `22:2592-2631`), and whether
  that write records `accounts.enable_trading` (`ACT:135`) is D03-Q4. Deleted: the row leaves the
  list, and a notice under the `h1` reads "sub_002 · LIVE deleted — history kept. Its keys still
  work at Bybit until you delete them there." (polite once; `D02:752-753`, `D02:270`). Focus after
  a disable returns to the row's Actions button; after a delete, whose opener is gone, it moves to
  the notice (`tabindex="-1"`; PROPOSED).
§ spec ‖ 8. SCR-079 — Account detail drawer, and SCR-019'
@ prose
  What a role sees is what the server serves to it (D15, `D02:201`): the Owner gets the key facts;
  a Manager and a Viewer get the key status and health in words, and nothing else of the key
  (`24:4766`; `D02:806-814`).
@ prose
  Every write in the drawer is gated in the server's leg order, the view-as leg first (T2 per
  §10.1; the gated set and who sees what are §10.2).
@ prose
  A stale balance keeps full contrast (C-10, `D02:1205`; CD-4, `MEMO:379`).
@ prose
  No secret is displayed, ever (`14:1753`; D13, `D02:199`): the one key value is CMP-034's
  `...{last4}` (§2.3, BQ-8).
@ head 3
  Size · tokens
@ row Drawer ‖ Size · tokens
  `color.surface.overlay` under `elevation.dialog`; the edge `color.border.default` (decorative,
  §9 `hairline`); no `size.drawer` token exists, so 480 is the consumed geometry, not a token
@ row Balances ‖ Block
  Balances
@ row Balances ‖ Content and copy
  the caption "Balances · as of {hh:mm:ss} UTC" (CMP-036 `freshness`); a two-column `dl` of
  CMP-036 rows — Equity, Wallet balance, Available balance, Unrealised PnL (CMP-116),
  Initial-margin rate, Realised PnL today (CMP-116), Maint.-margin rate — every figure with its
  unit; used margin is the initial-margin rate in % until O-E serves it in USDT, and fees and
  funding are not drawn until a field serves them
@ row Key and health — the Owner ‖ Block
  Key and health — the Owner
@ row Key and health — the Owner ‖ Content and copy
  `h3` "Key and health"; the key line, "API key {key_id_masked} · {status} · Rotation due {date}
  UTC · Bybit expiry: none" (CMP-034, the served status, both clocks, D7; from `listApiKeys`,
  `keys:read`); the permission summary as a `ul` of plain statements, CMP-175's `key` facets in
  sentence form — "Trade: yes." "Withdrawal: off — verified 14:02 UTC." "IP allowlist: matches." —
  where "off" appears only for a fresh pass and always with its time, the key's `last_verified_at`
  (AD-3, `MEMO:399`; D03-C15), every other state takes its own statement
  (`e27.scr079.key.statements.other`; `15:2046`; D4), and the critical state is never a statement:
  its list item is the CMP-175 critical badge — the octagon, the bold "BLOCKED — fund right found"
  and the 2 px `border.thick` `color.status.danger.strong` border (§2.1;
  `e27.cmp175.withdrawal_detected`); CMP-178 inline, "Health: healthy · heartbeat 2 s"; "Rate
  budget: 72 % free (deployment)"
@ row Key and health — any other role ‖ Block
  Key and health — any other role
@ row Key and health — any other role ‖ Content and copy
  "API key: {status}" and "Health: {state} · heartbeat {n} s", in words; no rights or allowlist
  statement, no egress IP, no rate budget
@ row The drawer's one notice ‖ Content and copy
  when a state blocks every write — key rejected, disabled, no key, view-as — one CMP-028 notice
  under the header in BQ-9's silent form (no live role of its own; a stable id); every gated
  write's `aria-describedby` points at it (one notice, many pointers)
@ row The drawer's one notice ‖ Size · tokens
  key rejected: tone danger, `color.text.primary` on `color.status.danger.subtle` with the octagon
  in `color.status.danger.strong` (§9 `c175-danger-word`, `c175-danger-glyph`); disabled, no key,
  view-as: tone info, `color.status.info.subtle` with `color.status.info.strong` (§9
  `c175-info-word`, `c175-info-glyph`)
@ prose
  The Owner's statements are plain text led by their class glyphs, so a fund right found drawn as
  one more statement would read like "IP allowlist: no match.", a failed state; it is the CMP-175
  critical badge instead, the list item itself, with its bold word and its 2 px border.
@ prose
  No E27-D02 frame draws a blocked key in the drawer; CMP-175's WithdrawalDetected story carries
  the form (§13).
@ prose
  At 720 CSS px wide or less — 200 % zoom on the 1280 × 800 frame is 640 — the drawer takes the
  full width and its balance columns stack (`D02:1089-1090`; §11).
@ prose
  **Light and high contrast.** Every binding above is a token, so the light frame is the same
  names in `semantic-light`, and §9 measures every pair in dark, light and high contrast.
@ prose
  Two light readings need the shape: the octagon of a rejected key and the triangle of a rotation
  due share one hue in light (DS-6; §9 `glyph-critical-warning` is 0.00 <!--
  audit:cvd.glyph-critical-warning.light.normal=0.00 --> there), so the glyph shape and the words
  carry them; and the stale chip's clock is 3.37 <!-- audit:pairs.stale-glyph.light=3.37 --> in
  light (`stale-glyph`), over the 3.0 bar, with its words beside it.
@ prose
  Every role: `GET /exchange-accounts/{accountId}` (`balance`, `balance_stale`,
  `balance_stale_since`, `health`, `key_status`, the modes, `enabled`), `wallet` and `positions`.
@ prose
  The Owner adds `GET /exchange-accounts/{accountId}/keys`, `GET /admin/security/summary` for the
  rights and allowlist words — `not_mounted` at the base (`MX:202-208`), so until it is mounted
  those statements are the target state, stamped "not yet served — G-1, #895 / #896" on the board
  annotation layer (D20, `D02:206`) — and `system` `exchange.rate_budget_free_pct`.
@ prose
  **The hi-fi rows.** Each row draws the anatomy above with the one block it changes; the Board
  cell is the frame's board, and the light reading is the same tokens in `semantic-light` (above).
@ head 4
  Hi-fi (dark; light by token)
@ head 5
  Tokens
@ head 6
  Copy keys
@ row 62 ‖ Copy keys
  `e27.scr079.h2`, `e27.scr079.balances.*`, `e27.scr079.key.line`, `e27.scr079.key.statements`,
  `e27.scr079.health`, `e27.scr079.rate_budget`, `e27.scr079.profile`, `e27.scr079.links`,
  `accounts.mode_locked`
@ row 63 ‖ Frame (E27-D02 §7)
  `SCR-079 / key expiring soon`
@ row 63 ‖ Hi-fi (dark; light by to
  the Owner's drawer with the key line changed: "Rotation due in 12 d · 2026-11-04 UTC" or "Bybit
  expiry in 9 d", each led by the triangle, never one chip mixing the two clocks (D7, AD-5); the
  other roles see no expiring state, because `key_status` serves none; the mode controls stay T2
  `accounts.mode_locked`, the CMP-019 `lock` (CMP-079 RbacGate) leading each segment
@ row 64 ‖ Frame (E27-D02 §7)
  `SCR-079 / key invalid`
@ row 64 ‖ Hi-fi (dark; light by to
  the drawer's one notice, tone danger with the octagon: "This account's API key was rejected —
  trading is off."; Change leverage… and both mode controls are T2 `accounts.key_rejected`, each
  led by the CMP-019 `lock` (CMP-079 RbacGate), and point at it; the Owner's drawer adds "Rotate
  it or revoke it in Admin → Accounts." under it, in a node no control points at; the transition
  is announced assertively once (D21; §11)
@ row 65 ‖ Copy keys
  `e27.scr079.key.statements.other`, `e27.scr079.ip_mismatch`, `e27.shared.copy`,
  `accounts.mode_locked`
@ row 66 ‖ Frame (E27-D02 §7)
  `SCR-079 / stale balance`
@ row 67 ‖ Hi-fi (dark; light by to
  a Manager with the trade grant: balances with their freshness, positions and Change leverage…
  enabled, both mode controls T2 `rbac.owner_only`, each led by the CMP-019 `lock` (CMP-079
  RbacGate) ("Only the owner can change account settings."); the key block reduced to "API key:
  active" and "Health: healthy · heartbeat 2 s"; no profile links (T3)
@ row 67 ‖ Copy keys
  `e27.scr079.key.status`, `e27.scr079.health`, `rbac.owner_only` ({verb} "change account
  settings")
@ row 68 ‖ Hi-fi (dark; light by to
  as the Manager, and Change leverage… T2 `rbac.permission`, led by the CMP-019 `lock` (CMP-079
  RbacGate) ("Your role can't change positions."); the balance block is not drawn until `24`
  defines masked balances (OQ-6), a "not yet served" strip on the board, never an invented masking
@ row 69 ‖ Class
  T2 per §10.1 (view-as leg first)
@ row 69 ‖ Hi-fi (dark; light by to
  the Owner viewing as alex sees alex's drawer: the one notice "Read-only while viewing as alex."
  (tone info), and Change leverage… and both mode controls T2 `rbac.view_as`, each led by the
  CMP-019 `lock` (CMP-079 RbacGate), the view-as leg checked before every other; a forced write is
  refused `view_as_read_only` (T4) and recorded `admin.view_as_refused`
@ row 71 ‖ Frame (E27-D02 §7)
  `SCR-079 / no API key yet`
@ row 71 ‖ Hi-fi (dark; light by to
  the one notice "No API key yet — trading is off for this account." (tone info) and every write
  T2 `accounts.no_key`, each led by the CMP-019 `lock` (CMP-079 RbacGate); the Owner's drawer adds
  the untimed account-level 48 h line when the account never held a key (D16; C-9)
@ prose
  The card's two account tasks are steps of CMP-097's ordered list with read-only checkbox
  semantics (`aria-checked` reflects completion), each a CMP-021 link to the screen that completes
  it (`14:485`): "Register a Bybit account" to SCR-126's register step and "Add its API key" to
  SCR-126's key step.
@ prose
  The Owner's done line names the key and its verified time, both read from `listApiKeys`
  (`keys:read`) and never from the checklist: `OnboardingChecklist.items[]` carries only `key`,
  `state`, `reason`, `unblock_at` and `action_route` (`22:21029-21047`) on a read with
  `permissions: []`, and stays free of key facts, so any other role's done line names no key fact
  (D15).
@ head 5
  Copy keys
@ row 76 ‖ Copy keys
  `e27.scr019.task.register`, `e27.scr019.task.key`, `e27.scr019.error`
@ row 77 ‖ Content (strings in §12.
  "Bybit account registered"; "API key added — key ...a7b8 verified 14:02 UTC" for the Owner, "API
  key added" for any other role; `setup.task_completed` (analytics)
@ row 77 ‖ Copy keys
  `e27.scr019.done.register`, `e27.scr019.done.key`, `e27.scr019.done.key_other`
@ row 78 ‖ Content (strings in §12.
  a Manager's tasks stay listed, each led by the CMP-019 `lock` (CMP-079 RbacGate),
  `aria-disabled`, the reason as the step's second line — `rbac.owner_only` with {verb} "change
  account settings" on `sub_account` and "manage API keys" on `api_key` — and the admin link
  dropped; the Owner's `blocked` item renders through a registered key: `keys.kek_unavailable`,
  `pending_key.untimed`, or E30-D02's timed `pending_key` once `unblock_at` carries a recorded
  time (O-C)
@ row 78 ‖ Copy keys
  `rbac.owner_only` ({verb} "change account settings" or "manage API keys"),
  `pending_key.untimed`, `keys.kek_unavailable`
§ spec ‖ 9. Contrast, greyscale and colour vision — the m
@ prose
  The tool layers the token JSON as `packages/ui/tokens/themes.json` does — dark is the primitives
  plus `semantic-dark`, light adds `semantic-light`, high contrast adds `semantic-hc` — through
  `packages/ui/tokens/tests/verify_tokens.py`; it takes every ratio from
  `contrast_check.contrast_ratio()` (`docs/design/_tools/contrast_check.py`) and every
  colour-vision value from `docs/research/_tools/cvd_simulate.py` (`simulate`, `delta_e76`),
  imported and never re-implemented (BQ-16).
@ prose
  **Counts.** 62 rows: 57 gated <!-- audit:numbers.pairs_rows=57 -->, of which 29 are registered
  in `tools/contrast/pairs.mjs` <!-- audit:numbers.pairs_registered=29 --> and 28 are PROPOSED for
  the token owner <!-- audit:numbers.pairs_proposed=28 --> (a design PR never edits `tools/`); 5
  are reported <!-- audit:numbers.pairs_reported=5 -->; 0 FAIL <!-- audit:numbers.pairs_fail=0
  -->; 19 rows reproduce a merged spec's numbers to the hundredth <!-- audit:numbers.repro_rows=19
  -->, and 0 of them are off <!-- audit:numbers.repro_fail=0 -->.
@ prose
  A `CR:` row is measured on the token its change request would alias, never on an invented hex.
@ prose
  **The matrix, in the tool's order** (light and high contrast are the same token names resolved
  in their sets):
@ row 1 ‖ Where
  CMP-175 pass words (verified, trade-only) on their fill
@ row 2 ‖ Where
  CMP-175 check glyph on the pass fill
@ row 3 ‖ Where
  CMP-175 critical and failed words (withdrawal-detected, IP-missing, IP-mismatch, expired,
  read-only on import); the blocked row's line 1; the KEK notice; the destructive confirm (E42-D02
  D3) — reproduces BQ-6 to the hundredth ✓
@ row 4 ‖ Where
  CMP-175 octagon on the critical and failed fill; the destructive confirm's border
@ row 6 ‖ Where
  CMP-175 warning words (expiring, check overdue)
@ row 7 ‖ Where
  CMP-175 triangle and clock on the warning fill
@ row 8 ‖ Where
  CMP-175 "not checked" (dash) on the neutral fill
@ row 9 ‖ Where
  CMP-175 dash; CMP-011's neutral label (the OK chip)
@ row 10 ‖ Where
  CMP-175 stored read-only (BQ-5 rider)
@ row 11 ‖ Where
  CMP-175 info glyph on the info fill
@ row 19 ‖ Where
  CMP-176 line 1 (label, UID, environment word), CMP-034's `...{last4}`, a disabled row at full
  contrast — reproduces E30-D01 §3 to the hundredth ✓
@ row 20 ‖ Where
  CMP-176 line 2 (allowlist, key age, rotation due); the T2 reason — reproduces E09-D09 §11 to the
  hundredth ✓
@ row 39 ‖ Where
  dialog and drawer title and body; the masked id in a dialog; the absolute overlap time —
  reproduces E42-D02 §11 to the hundredth ✓
@ prose
  **Reported, not gated — two readings for the token owner.** (1) `color.text.link` has no
  high-contrast override (`semantic-hc.tokens.json` overrides 14 tokens <!--
  audit:numbers.token_files.hc=14 -->, the link not among them): a link on the row measures 6.66
  <!-- audit:pairs.row-link.high-contrast=6.66 --> in high contrast, over the 4.5 text bar this
  matrix gates and under the 7:1 body-text aim of the high-contrast theme (`05:130`); its dialog
  and drawer twin, `link-overlay` (row 62), measures 6.15 <!--
  audit:pairs.link-overlay.high-contrast=6.15 --> there, the "6.15:1 in HC" <!--
  audit:pairs.link-overlay.high-contrast=6.15 --> the registry holds out
  (`tools/contrast/pairs.mjs:193`).
@ prose
  CMP-021 underlines every link (`15:247`), so no link depends on its colour; the retune is the
  token owner's, routed as D03-H7 (§14).
@ prose
  **Colour vision (AC2) — reported, never gated.** Colour reinforces and never carries a CMP-175
  state: the tool gates the carriers in §2.1 instead — a word of its own, the glyph of its
  severity class, and the critical state's bold word and 2 px border (BQ-6) — and reports Delta
  E76 (CIE76) under protanopia, deuteranopia and tritanopia against the 5.0 JND
  (`cvd_simulate.py`).
@ prose
  The subtle fills are never the carrier: "BLOCKED — fund right found", the octagon, the bold and
  the border are.
@ prose
  - **The not-checked fill in light:** against the pass fill under tritanopia 4.81 <!--
  audit:cvd.fill-unknown-pass.light.tritanopia=4.81 -->, against the critical fill under
  protanopia 3.15 <!-- audit:cvd.fill-unknown-critical.light.protanopia=3.15 -->; the dash and
  "Withdrawal: not checked" carry it, and it never reads as a pass (AD-2).
@ prose
  601 luma per token** (`int(0.299 r + 0.587 g + 0.114 b)`; reported):
@ head 1
  Token
@ prose
  In greyscale the subtle fills do not separate the states — in dark they span 38 <!--
  audit:luma.color.status.danger.subtle.dark=38 --> to 52 <!--
  audit:luma.color.status.warning.subtle.dark=52 --> — and in light the danger and warning glyph
  tokens are both 108 <!-- audit:luma.color.status.danger.strong.light=108 -->.
@ row CMP-175 and CMP-011 fills ‖ Carrier
  CMP-175 and CMP-011 fills
@ row State glyphs (check, octagon, triangle, ‖ Normally
  `.strong` tokens or `color.text.secondary`, as `currentColor` strokes
@ prose
  **Token bindings per element** (every name a token at the base; geometry is §2's):
@ row CMP-175 pass (verified, trade-only) ‖ Element
  CMP-175 pass (verified, trade-only)
@ row CMP-011 "OK" chip ‖ Ink and glyph
  `color.text.secondary`, check in the same token (CMP-011's neutral form, BQ-7)
@ row CMP-175 critical (withdrawal-detected) ‖ Element
  CMP-175 critical (withdrawal-detected)
@ row CMP-175 failed (IP-missing, IP-mismatch, ‖ Element
  CMP-175 failed (IP-missing, IP-mismatch, expired, read-only at import)
@ row CMP-175 warning and time warning (expiri ‖ Element
  CMP-175 warning and time warning (expiring; check overdue)
@ row CMP-175 unknown (not checked) ‖ Element
  CMP-175 unknown (not checked)
@ row CMP-175 info (a stored read-only key, co ‖ Element
  CMP-175 info (a stored read-only key, component level only)
@ row The verdict line on the page ‖ Ink and glyph
  `color.text.primary`; its time and basis `color.text.secondary`; check, octagon or clock in the
  `.strong` tokens
@ row CMP-178 inline health ‖ Ink and glyph
  the word in `color.text.primary`; check, triangle or octagon in the `.strong` tokens
@ row Fields (CMP-201 write-only; the typed la ‖ Element
  Fields (CMP-201 write-only; the typed label)
@ row CMP-028 notices (the KEK notice; the dra ‖ Ink and glyph
  `color.text.primary`; octagon or info in the `.strong` token
@ prose
  **Design-system change requests** (no hex invented; no token edited by this PR):
@ prose
  The frames bind `color.text.tertiary` directly until the alias merges, so AC5 rests on no
  unmerged token: SCR-126's key and secret fields, SCR-127 stage 2, SCR-016 step 3 and SCR-129's
  typed field.
@ prose
  - **The link in high contrast** (reading 1 above) — not a DS id: a hand-off to the token owner,
  D03-H7 (§14).
§ spec ‖ 10.1 The T2 rule (stated once)
@ prose
  **Legs, in the server's order** (E09-D09 §2.1; `22:281-290`): the view-as leg first on every
  write — `rbac.view_as`, "Read-only while viewing as {user}." — because the server refuses
  `view_as_read_only` before it authorises; then the permission or owner-only leg
  (`rbac.permission`, `rbac.owner_only`, each with its {verb} from E09-D09 §3.2), then the grant
  (`rbac.account_read_only`), then the environment (`rbac.env`), and last a registered state — the
  ten PROPOSED E27 keys of §12.2 (vocabulary owner E27, registration routed by C-9, `D02:1204`)
  and E30-D02 §14's `frozen`, `lockout` and `arm.locked`, consumed; the first leg that holds gives
  the reason.
@ prose
  **Semantics:** the control keeps its native role and its full label; `aria-disabled="true"`,
  never the `disabled` attribute, so it stays in the Tab order and a menu item stays
  arrow-reachable; the reason node is in the DOM at mount and linked by `aria-describedby`; where
  one state blocks a whole panel or drawer, one notice carries the reason and every gated control
  points at it — one notice, many pointers (the KEK notice of BQ-9, SCR-079's key-rejected,
  disabled, no-key and view-as notices).
@ prose
  **Keys:** `Enter`, `Space`, a bound hotkey or an arrow onto a T2 radio changes nothing and
  re-shows the reason inline with one polite announcement; `↑` and `↓` land on a T2 menu item
  without activating it (E09-D09 §9.3).
§ spec ‖ 10.2 The gated set
@ prose
  E27-D02's eight rows (`D02:1016-1025`) carried into hi-fi; the legs in the server's order, any
  view-as leg first, each with its reason key (§12.2).
@ head 3
  Legs in order → reason key
@ row Verify and save; Add a key… (`createApiK ‖ Control (operation)
  Verify and save; Add a key… (`createApiKey`)
@ row Verify and save; Add a key… (`createApiK ‖ Legs in order → reason k
  KEK unavailable → `keys.kek_unavailable` (one notice, many pointers: the CMP-028 KEK notice)
@ row Rotate key… (`rotateApiKey`) ‖ Control (operation)
  Rotate key… (`rotateApiKey`)
@ row Rotate key… (`rotateApiKey`) ‖ Legs in order → reason k
  KEK unavailable → `keys.kek_unavailable`; a fund right found on the key, once G-1 attributes it
  → `keys.compromise_path`
@ row Test key… (`testApiKey`) ‖ Control (operation)
  Test key… (`testApiKey`)
@ row Test key… (`testApiKey`) ‖ Legs in order → reason k
  KEK unavailable → `keys.kek_unavailable`; `pending`, `invalid` or `expired` →
  `keys.not_signable`; this client's own test under a minute ago → `keys.test_throttled`, its time
  from the server's `checked_at`, never the client clock
@ row Delete (keeps history)… (`deleteExchange ‖ Legs in order → reason k
  the account never had a key → `accounts.never_keyed`; Disable… stays enabled
@ row Change leverage… (`setPositionLeverage`) ‖ Legs in order → reason k
  view-as → `rbac.view_as`; Viewer → `rbac.permission` ({verb} "change positions"); a `read` grant
  → `rbac.account_read_only`; LIVE without `live` → `rbac.env`; disabled → `accounts.disabled`;
  key rejected → `accounts.key_rejected`; no key → `accounts.no_key`; then E30-D02's `frozen`,
  `lockout`, `arm.locked` (consumed)
@ row Position mode, margin mode (`updateExcha ‖ Legs in order → reason k
  view-as → `rbac.view_as`; Manager, Viewer → `rbac.owner_only` ({verb} "change account
  settings"); disabled → `accounts.disabled`; key rejected → `accounts.key_rejected`; no key →
  `accounts.no_key`; open positions or orders → `accounts.mode_locked`
@ row Tasks `sub_account`, `api_key` (CMP-097 ‖ Legs in order → reason k
  a Manager or a Viewer — or the Owner viewing as one, whose self-scoped read answers as the
  target (`D09:95`) — → `rbac.owner_only` ({verb} "change account settings" on `sub_account`,
  "manage API keys" on `api_key`), the admin link dropped; the Owner's `blocked` →
  `keys.kek_unavailable`, `pending_key.untimed` or E30-D02's `pending_key`
@ head 3
  SCR-079 key facts (rights, allowlist, egress IP, rate budget)
@ head 4
  SCR-079 key status and health
@ head 5
  SCR-079 balances
@ row Manager, trade grant ‖ SCR-079 key status and h
  "API key: {status}"; health in words
@ row Viewer ‖ SCR-079 balances
  not drawn until `24` defines masked balances (OQ-6)
§ spec ‖ 10.3 What is NOT T2
@ prose
  None of these draws a lock, takes CMP-079 or names a reason key:
@ prose
  - **Busy** — Verify and save, Run test and Verify and switch while their own request runs:
  CMP-001's `loading` with `aria-busy="true"`, focusable, the validating copy beside it (D18); a
  key in its overlap, "Rotation in progress · old key usable until {hh:mm:ss} UTC"
  (`e27.scr125.busy.overlap`).
@ prose
  - **Outcome** — an action done or no longer applicable shows its outcome line instead (#960
  Q13): an import on an account with an active key is the key row with Rotate (AD-1); "Revoked at
  {hh:mm} UTC — delete it at Bybit"; "Disabled at {hh:mm} UTC — doesn't trade here." with Enable…;
  a passed Test's result line; stage 5's done line.
@ prose
  - **The validity look** — form validity, E42-D03's form for a rung confirm (`E42-D03:542`,
  `E42-D03:566-567`), adopted for CMP-044 by BQ-11 in place of E30-D02's dimmed look
  (`E30-D02:128`): a rung-3 confirm before the summary has loaded is not rendered at all (Cancel
  only); after it, until the typed label matches and, where there are two, a radio is chosen, the
  confirm stays focusable with `aria-disabled`, its danger fill dropped to `color.surface.raised`
  with a `color.border.default` hairline, its label `color.text.tertiary` and its hint in
  full-opacity `color.text.secondary` under it — no lock, no CMP-079, no key (layer
  `validity-reason`); empty key fields show an inline error on press (CMP-040).
§ spec ‖ 11. Keyboard, focus and live regions (board 10)
@ row SCR-125 (`/admin/accounts`) ‖ Role · initial focus
  landmarks: the band (`role="region"` "Admin area"), the strip, the `h1`, the regions "Suspected
  compromise" (only while a response is open), "Accounts" and "Key health and secrets policy"; the
  skip link lands on the `h1`
@ row SCR-125 (`/admin/accounts`) ‖ Tab order
  skip link → strip items → + Add account → per row in order: [Start the compromise response] (a
  blocked row only, first), Actions for {label} · {ENV}, Details for {label} · {ENV} → the SCR-128
  disclosure → SCR-128's per-key Actions → the footer; a plain `<table>` with a caption, two
  header rows and `th scope="row"` on the label: no grid and no roving tabindex (D22)
@ row SCR-126 add ‖ Tab order
  register: Label → Bybit UID → Kind → Parent (a sub only) → Cancel → Register account; key step:
  Copy (drawn as the target state until the egress-IP read is served, BQ-15 item 7; D03-G1) → API
  key → API secret → Cancel → Verify and save
@ row SCR-126 add ‖ `Esc` · focus return
  after an answer focus moves to the result heading (the user's press moved it); leaving the page
  clears both secret fields
@ row SCR-126 edit ‖ Tab order
  Label → Rotate key… (Add a key… when keyless) → Disable… → Delete (keeps history)… → Cancel →
  Save (PROPOSED: E27-D02 names no order)
@ row SCR-016 step 3 ‖ Tab order
  Label → Bybit UID → API key → API secret → Copy (the target state before any check, BQ-15 item
  7) → Verify and save → Back → Skip for now → Continue, the step's own order (`D02:850-860`)
@ row SCR-127 wizard ‖ `Esc` · focus return
  `Esc` = Cancel at stages 1, 2 and 5; at stages 3 and 4 it closes the view only, the server's
  rotation continues and the row's busy line shows it; focus returns to the opener (the row's
  Actions button, or SCR-126's Rotate key…)
@ row SCR-006 step-up (E09-D06, consumed) ‖ Role · initial focus
  `role="alertdialog"`; the password field
@ row SCR-006 step-up (E09-D06, consumed) ‖ Tab order
  password → code → Cancel → Confirm
@ row Compromise card (a region of SCR-128) ‖ Tab order
  Freeze {label}… → the Bybit note checkbox → Revoke here… → Add a new key… → Close card
@ row SCR-125 list ‖ 150 % text scale
  rows grow (`min-height`: the row tokens are fixed px, `16:138`); chips wrap to a second line and
  never truncate
@ row SCR-128 key table ‖ Surface
  SCR-128 key table
@ row SCR-128 key table ‖ 200 % zoom (640 × 400 CS
  one card per key under its LIVE or DEMO heading
@ row SCR-079 drawer ‖ 200 % zoom (640 × 400 CS
  full width at 720 CSS px or less (E08-D06 D-14); the balance columns stack; the header stays one
  sticky row
@ row a row chip turns BLOCKED, Key refused, I ‖ Event
  a row chip turns BLOCKED, Key refused, IP allowlist: no match or Down
@ row SCR-079's balances refresh ‖ Event
  SCR-079's balances refresh
@ row an SCR-079 balance turns stale ‖ Event
  an SCR-079 balance turns stale
@ row SCR-079's key is rejected while the draw ‖ Event
  SCR-079's key is rejected while the drawer is open
§ spec ‖ 12.1 The deck
@ prose
  Every product string the eight screens, the cross-screen patterns and the contributed components
  show, keyed so that a screen cites a key and never writes its own string (the ticket's Technical
  notes; BQ-15).
@ prose
  `{…}` are fills; every time reads UTC (`D02:178`); a key id is `...` plus 4 (D13).
@ prose
  The tool's copy gate holds every string here: no "reveal", "irreversible", "permanently",
  "step-up", "re-authentication", "Bybit says" or "n/a"; "expiry" only with Bybit's name (AD-5);
  every clock time followed by UTC, or "left" for a duration; a withdrawal "OFF" or "off" only
  beside its verified time (AD-3); no withdrawal or transfer right drawn as allowed.
@ prose
  The ticket's six required items are marked **required** in Where: the withdrawal verdict
  (`e27.scr125.verdict.*`, `e27.cmp175.withdrawal_detected`, `e27.scr125.blocked.line2`, the
  import refusal `e27.scr126.refused.withdrawal`, the onboarding result row `e27.scr016.result`,
  the drawer's statements); the IP-mismatch remediation with the allowlist set in Bybit's
  dashboard (CD-3's two forms, CP-3 at the allowlist row and stage 1, `e27.scr079.ip_mismatch`,
  `e27.scr129.unknown.fixable`, policy 4); the stale-balance badge (`e27.scr079.stale` and its
  CD-4 suffix); the irreversible-delete warning, met without that word
  (`e27.scr129.delete.history`, BQ-15 item 8); revoke and leave positions versus flatten first
  (`e27.scr129.choice.*` and the confirm labels); and the write-only secret explanation (CP-1 on
  every secret field, `e27.scr126.edit.write_only`, `e27.scr128.policy.write_only`,
  `e27.cmp034.description`).
@ row `e27.shell.strip.withdrawal` ‖ Id
  `e27.shell.strip.withdrawal`
@ row `e27.shell.strip.withdrawal` ‖ Where
  SCR-125 strip item, first while a fund right is found · frame 13
@ row `e27.shell.strip.withdrawal` ‖ String
  "Attention: {ENV} — a key on {label} can move funds → Start the compromise response"
@ row `e27.shell.h1` ‖ String
  "Bybit accounts and keys"
@ row `e27.shell.region.health` ‖ String
  "Key health and secrets policy"
@ row `e27.shell.grace.keys` ‖ Id
  `e27.shell.grace.keys`
@ row `e27.shell.grace.keys` ‖ Where
  the band's grace line and every `keys` ask line inside the window
@ row `e27.shell.grace.keys` ‖ String
  "Still trusted for key changes · {m:ss}"
@ row `e27.shell.grace.keys` ‖ Status · source
  refined · E42-D03:608 `grace` with {class} = key changes (D02:173-174; the time from
  `step_up_expires_at`, never a client clock)
@ row `e27.shell.banner.kek` ‖ String
  "Trading disabled: the credential key is unavailable."
@ row `e27.shell.banner.key_failed` ‖ String
  "Trading disabled: a stored API key failed its check."
@ row `e27.shell.banner.key_stale` ‖ String
  "Trading disabled: a stored API key has no recent passing check."
@ row `e27.shell.banner.key_unchecked` ‖ String
  "Trading disabled: the stored API keys could not be checked."
@ row `e27.shell.notice.deleted` ‖ String
  "{label} · {ENV} deleted — history kept. Its keys still work at Bybit until you delete them
  there."
@ prose
  **The withdrawal verdict line** (frame 2; CMP-175 `aggregate`, BQ-5; D3, `D02:189`).
@ row `e27.scr125.verdict.dated` ‖ Where
  CMP-175 `aggregate`, under the `h1` · frames 2, 6 (**required: the withdrawal verdict**)
@ row `e27.scr125.verdict.dated` ‖ String
  "Withdrawal: OFF on all {n} accounts with a key ✓ · verified {hh:mm} UTC"
@ row `e27.scr125.verdict.dated` ‖ Status · source
  refined · CD-1 (+ “with a key”, D02:222; fills)
@ row `e27.scr125.verdict.overdue` ‖ Where
  CMP-175 `aggregate` · frame 2 (**required: the withdrawal verdict**)
@ row `e27.scr125.verdict.overdue` ‖ String
  "Withdrawal check overdue — last passed {hh:mm} UTC. Trading is read-only until a restart passes
  the check."
@ row `e27.scr125.verdict.failed` ‖ Where
  CMP-175 `aggregate` · frames 2, 13, 14 (**required: the withdrawal verdict**)
@ row `e27.scr125.verdict.failed` ‖ String
  "A stored key failed its check — trading is read-only for everyone until the key is fixed or
  revoked here and a restart passes the check, and order entry on that key's account stays
  disabled by policy until it is turned back on."
@ row `e27.scr125.verdict.failed` ‖ Status · source
  refined · CD-2, the failed form: its account clause takes E30-D02:437's words (BQ-15 item 4);
  “that key's account”, not {account}, because the notice names no key and no account
  (23:4270-4271)
@ row `e27.scr125.verdict.unavailable` ‖ Where
  CMP-175 `aggregate` · frame 2
@ row `e27.scr125.verdict.unavailable` ‖ String
  "Withdrawal check could not run — trading is read-only until a restart passes the check."
@ row `e27.scr125.verdict.read_failed` ‖ Where
  CMP-175 `aggregate` · frame 8
@ row `e27.scr125.verdict.read_failed` ‖ String
  "Withdrawal verdict unavailable — the accounts could not be read."
@ row `e27.scr125.verdict.no_keys` ‖ Where
  CMP-175 `aggregate` · frames 2, 7
@ row `e27.scr125.verdict.no_keys` ‖ String
  "No stored keys yet — nothing to check."
@ row `e27.scr125.verdict.loading` ‖ Where
  CMP-175 `aggregate`, never OFF · frame 8
@ row `e27.scr125.verdict.loading` ‖ String
  "Withdrawal verdict loading…"
@ row `e27.scr125.verdict.audit_hint` ‖ String
  "Find the key in the audit log: action account.tested."
@ row `e27.checks.names` ‖ String
  "Environment" · "Withdrawal and transfer" · "Other rights" · "Trade access" · "Unified account"
  · "UID" · "IP allowlist" · "Bybit expiry" · "Signed probe and clock"
@ row `e27.checks.env.passed` ‖ String
  "passed — this key belongs to {ENV}"
@ row `e27.checks.env.failed` ‖ String
  "This key doesn't belong to {ENV}."
@ row `e27.checks.withdrawal.passed` ‖ Id
  `e27.checks.withdrawal.passed`
@ row `e27.checks.withdrawal.passed` ‖ Where
  Withdrawal and transfer row, a fresh pass only (`15:2046`; D4, AD-2), dated (D03-C15) · frames
  3, 21, 36
@ row `e27.checks.trade.passed` ‖ String
  "passed — a trade key"
@ row `e27.checks.trade.failed` ‖ Where
  Trade access row, and CMP-175's read-only word at import (§2.1) · frame 26
@ row `e27.checks.uid.failed` ‖ String
  "This key belongs to another Bybit UID."
@ row `e27.checks.expiry.failed` ‖ String
  "This key has expired at Bybit."
@ row `e27.scr125.table.caption` ‖ String
  "Bybit accounts and their keys, grouped LIVE then DEMO"
@ row `e27.scr125.table.headers` ‖ String
  "label · UID · env" · "state" · "key · rights" · "actions" · "IP allowlist" · "key age ·
  rotation due" · "health"
@ row `e27.scr125.row.key` ‖ Id
  `e27.scr125.row.key`
@ row `e27.scr125.row.key` ‖ Where
  CMP-176 line 1, CMP-034 + CMP-175 `key` facets · frames 6–17
@ row `e27.scr125.row.key` ‖ String
  "{key_id_masked} · Trade · Withdrawal OFF ✓ · verified {hh:mm} UTC"
@ row `e27.scr125.row.allowlist` ‖ Where
  CMP-176 line 2, CMP-175's allowlist facet in its header form: `e27.cmp175.allowlist_matches`
  without its "IP allowlist: " lead, which the column header gives (§2.1) · frames 6–17
@ prose
  **SCR-125 — the row's state** (CMP-176's state slot, one badge, the worst that applies, in
  §2.2's precedence: a CMP-011 chip below, or CMP-175's own word for a key-verification state —
  BLOCKED, Expired at Bybit, the two allowlist states, Check overdue, Withdrawal: not checked and
  Bybit expiry — keyed once under `e27.cmp175.*`; HD3).
@ row `e27.scr125.chip.key_refused` ‖ String
  "Key refused by Bybit"
@ row `e27.scr125.chip.no_key` ‖ String
  "No key — inactive"
@ row `e27.scr125.menu.items` ‖ String
  "Edit…" · "Add a key…" · "Rotate key…" · "Test key…" · "Revoke key…" · "Suspected compromise…" ·
  "Disable…" · "Delete (keeps history)…"
@ row `e27.scr125.menu.ask.keys` ‖ Id
  `e27.scr125.menu.ask.keys`
@ row `e27.scr125.menu.ask.keys` ‖ Where
  second line of Add a key…, Rotate key…, Revoke key… · frame 11
@ row `e27.scr125.menu.ask.keys` ‖ String
  "Asks for your password and a code"
@ row `e27.scr125.menu.ask.label` ‖ Where
  second line of Disable…, Delete…, and Revoke key… on the last key; the ask stamped “not yet
  served — G-8, #895 / #898” · frame 11
@ row `e27.scr125.menu.ask.label` ‖ String
  "Asks for your password, a code and the account's name"
@ row `e27.scr125.busy.overlap` ‖ String
  "Rotation in progress · old key usable until {hh:mm:ss} UTC"
@ row `e27.scr125.details.bybit_expiry` ‖ String
  "The key stops working at Bybit on {date} UTC — rotate before then."
@ row `e27.scr125.details.key_refused` ‖ String
  "Bybit no longer accepts key {key_id_masked} — it signs nothing. Rotate it, or revoke it here if
  you deleted it at Bybit."
@ row `e27.scr125.details.allowlist` ‖ String
  "CandleViewer accepts this key only if its IP allowlist holds exactly {egress_ip}. Set it in
  Bybit's dashboard [Copy], then test it again. It can't be set from here."
@ row `e27.scr125.blocked.line2` ‖ Where
  CMP-176 blocked row, line 2 · frame 13 (**required: the withdrawal verdict**)
@ row `e27.scr125.blocked.line2` ‖ String
  "This key can now withdraw or transfer — it was changed at Bybit. Trading is read-only for every
  account and off for {label}."
@ row `e27.scr125.test.title` ‖ String
  "Test {label}'s key {key_id_masked} · {ENV}"
@ row `e27.scr125.test.before` ‖ String
  "If this key fails its check, trading stops on every account until a restart passes the check,
  and trading on this account stays off until you turn it back on."
@ row `e27.scr125.test.passed_read_only` ‖ Where
  Test result line while a stored-key latch holds · frame 44
@ prose
  **SCR-126 — register, paste and save** (frames 18–21; CMP-065, CMP-040, CMP-201 write-only,
  CMP-036, CMP-033).
@ row `e27.scr126.stepper` ‖ String
  "Register the account" · "Add its API key"
@ row `e27.scr126.key.h2` ‖ Id
  `e27.scr126.key.h2`
@ row `e27.scr126.key.h2` ‖ Where
  key step `h2` · frames 19–29
@ row `e27.scr126.key.h2` ‖ String
  "API key for {label} · UID {uid} · {ENV} (this deployment)"
@ row `e27.scr126.key.instructions` ‖ Id
  `e27.scr126.key.instructions`
@ row `e27.scr126.key.instructions` ‖ Where
  key step, a static list (never boxes to tick, F-19) · frame 19
@ row `e27.scr126.key.instructions` ‖ String
  "Create the key in Bybit's dashboard with only:" · "Contract trade — Order and Position
  (Derivatives — DerivativesTrade is allowed too)" · "no withdrawal or transfer right" · "the IP
  allowlist below"
@ row `e27.scr126.allowlist.help` ‖ String
  "Set this key's IP allowlist in Bybit's dashboard to exactly {egress_ip} [Copy]. It can't be set
  here; CandleViewer only checks it."
@ row `e27.scr126.key.label` ‖ Id
  `e27.scr126.key.label`
@ row `e27.scr126.key.label` ‖ Where
  CMP-201 write-only field label and its first description · frames 19–29
@ row `e27.scr126.key.label` ‖ String
  "API key" · "value is write-only"
@ row `e27.scr126.secret.label` ‖ Id
  `e27.scr126.secret.label`
@ row `e27.scr126.secret.label` ‖ Where
  CMP-201 write-only field label · frames 19–29
@ row `e27.scr126.secret.label` ‖ String
  "API secret"
@ row `e27.scr126.secret.help` ‖ Id
  `e27.scr126.secret.help`
@ row `e27.scr126.secret.help` ‖ Where
  CMP-201 description, in the DOM at mount (`aria-describedby`) · frames 19–29, 72–75 (**required:
  the write-only secret explanation**)
@ row `e27.scr126.secret.help` ‖ String
  "Write-only: CandleViewer uses this secret to sign orders, and no one can see it again — not
  you, not an admin. If it is lost, create a new key at Bybit."
@ row `e27.scr126.marker` ‖ String
  "Recorded in the audit log · API key imported (api_key.import)"
@ row `e27.scr126.buttons` ‖ Where
  the key step's action, after `e27.shared.cancel` · frames 19–29
@ row `e27.scr126.validating` ‖ String
  "Checking the key with Bybit — environment, rights, withdrawal, IP allowlist, UID and clock…"
@ row `e27.scr126.saved` ‖ String
  "Saved. Key {key_id_masked} is active on {label}. Its secret can't be shown again."
@ row `e27.scr126.saved.live` ‖ String
  "Storing this key doesn't turn live trading on — that has its own gate."
@ row `e27.scr126.result.h3` ‖ String
  "Key check result"
@ row `e27.scr126.invalid.key_format` ‖ String
  "The API key is 8 to 128 characters."
@ row `e27.scr126.invalid.secret_format` ‖ String
  "The API secret is 8 to 256 characters."
@ row `e27.scr126.invalid.key_empty` ‖ String
  "Paste the API key."
@ row `e27.scr126.invalid.key_empty` ‖ Status · source
  new · D02:1037 (an empty key field shows an inline error on press)
@ row `e27.scr126.invalid.secret_empty` ‖ String
  "Paste the API secret."
@ row `e27.scr126.refused.withdrawal` ‖ Id
  `e27.scr126.refused.withdrawal`
@ row `e27.scr126.refused.withdrawal` ‖ Where
  the refusal; both fields cleared at once · frames 23, 74 (**required: the withdrawal verdict, at
  import**)
@ row `e27.scr126.refused.withdrawal` ‖ String
  "Refused: this key can withdraw or transfer, and nothing was stored. It still works at Bybit:
  delete it in Bybit's dashboard, then create a key with only the trading rights CandleViewer
  allows."
@ row `e27.scr126.refused.ip_bybit` ‖ String
  "Bybit refused requests from {egress_ip}. In Bybit's dashboard, set this key's IP allowlist to
  {egress_ip} [Copy] and nothing else, then verify again."
@ row `e27.scr126.refused.ip_rule` ‖ String
  "CandleViewer accepts this key only if its IP allowlist holds exactly {egress_ip}. Set it in
  Bybit's dashboard [Copy], then verify again. It can't be set from here."
@ row `e27.scr126.activation_failed` ‖ String
  "The key passed its checks but could not be switched on. It is stored revoked here and still
  works at Bybit — import it again, or delete it in Bybit's dashboard."
@ row `e27.scr126.edit.key_row` ‖ Where
  the key as an outcome row with [Rotate key…] · frame 31
@ row `e27.scr126.edit.key_row` ‖ String
  "API key {key_id_masked} · {status} · verified {hh:mm} UTC · Rotation due {date} UTC"
@ row `e27.scr126.edit.write_only` ‖ Where
  under the key row · frame 31 (**required: the write-only secret explanation**)
@ row `e27.scr126.edit.write_only` ‖ String
  "Write-only: the secret can't be shown or changed here; a new key goes through Rotate."
@ row `e27.scr126.stepup.title` ‖ Where
  SCR-006 (consumed, E09-D06) over the key step · frame 30
@ prose
  **SCR-016 step 3** (frames 72–75; the key fields are SCR-126's rows above).
@ row `e27.scr016.result` ‖ Where
  a result row the server fills, never a box (F-19) · frame 73 (**required: the withdrawal
  verdict**)
@ row `e27.scr016.result` ‖ String
  "Withdrawal and transfer: OFF ✓ — verified {hh:mm} UTC"
@ row `e27.scr016.continue_early` ‖ String
  "Verify and save the key first, or skip this step."
@ row `e27.scr016.skipped` ‖ String
  "Skipped — the key you add later goes through the same check."
@ prose
  **SCR-127 — the rotation wizard** (frames 33–41; CMP-066 `list`, CMP-035, CMP-201).
@ row `e27.scr127.title` ‖ String
  "Rotate the key of {label} ({key_id_masked}) · {ENV}"
@ row `e27.scr127.stage1.create` ‖ String
  "In Bybit's dashboard, create a new key for UID {uid} with only Contract trade — Order and
  Position, and no withdrawal or transfer right."
@ row `e27.scr127.stage1.h2` ‖ String
  "Create the new key at Bybit"
@ row `e27.scr127.stage1.allowlist` ‖ String
  "Set this key's IP allowlist in Bybit's dashboard to exactly {egress_ip} [Copy]. It can't be set
  here; CandleViewer only checks it."
@ row `e27.scr127.stage1.policy` ‖ Where
  stage 1, the key-age policy restated (`14:2555`) · frame 33
@ row `e27.scr127.stage1.policy` ‖ String
  "Keys are due for rotation every {n} days; this one is {age} days old (due {date} UTC). Overdue
  never stops trading."
@ row `e27.scr127.stage1.no_wait` ‖ String
  "Rotating doesn't start Bybit's 48 h wait: that applies to a new account's first key."
@ row `e27.scr127.stage2.h2` ‖ String
  "Paste the new key"
@ row `e27.scr127.stage2.lead` ‖ String
  "Open orders stay open. Both keys work for 15 minutes while requests drain."
@ row `e27.scr127.stage2.no_undo` ‖ String
  "Then the old key {old} is revoked here. There is no undo: to go back, rotate again."
@ row `e27.scr127.stage2.fields` ‖ Where
  CMP-201 write-only labels · frame 34
@ row `e27.scr127.stage2.fields` ‖ String
  "New API key" · "New API secret"
@ row `e27.scr127.secret.help` ‖ Id
  `e27.scr127.secret.help`
@ row `e27.scr127.secret.help` ‖ Where
  CMP-201 description at mount · frame 34 (**required: the write-only secret explanation**)
@ row `e27.scr127.secret.help` ‖ String
  "Write-only: CandleViewer uses this secret to sign orders, and no one can see it again — not
  you, not an admin. If it is lost, create a new key at Bybit."
@ row `e27.scr127.marker` ‖ String
  "Recorded in the audit log · API key rotated (api_key.rotate)"
@ row `e27.scr127.stage3.h2` ‖ String
  "Verifying the new key"
@ row `e27.scr127.stage3.refused` ‖ String
  "Nothing changed — the old key {key_id_masked} is still active."
@ row `e27.scr127.stage3.refused_h2` ‖ String
  "The new key was refused"
@ row `e27.scr127.stage3.new_key_lives` ‖ String
  "The new key still works at Bybit; delete it there if you won't use it."
@ row `e27.scr127.stage3.no_verdict` ‖ String
  "No answer from Bybit — nothing changed; the old key is still active. Try again in {n} s."
@ row `e27.scr127.stage4.switched` ‖ String
  "Switched at {hh:mm:ss} UTC. New requests use {new}. The old key {old} keeps working here until
  {hh:mm:ss} UTC — {mm:ss} left — while requests in flight finish. Open orders stay open."
@ row `e27.scr127.overlap.at60` ‖ String
  "1 minute left on the old key {old}, until {hh:mm:ss} UTC."
@ row `e27.scr127.overlap.at10` ‖ String
  "10 seconds left on the old key {old}, until {hh:mm:ss} UTC."
@ row `e27.scr127.stage5.h2` ‖ String
  "Old key revoked here"
@ row `e27.scr127.stage5.revoked` ‖ String
  "Revoked in CandleViewer. The key still works at Bybit until you delete it in Bybit's
  dashboard."
@ prose
  **SCR-128 — the key table and the secrets-at-rest policy** (frames 42–45).
@ row `e27.scr128.table.caption` ‖ String
  "Stored API keys, grouped LIVE then DEMO"
@ row `e27.scr128.table.headers` ‖ String
  "Account" · "Key" · "Status" · "Age" · "Rotation due" · "Rights" · "Allowlist" · "Actions"
@ row `e27.scr128.status` ‖ Where
  the Status cell, the key's `KeyStatus` as a word (`22:16092-16099`) · frames 42–45
@ row `e27.scr128.row.actions` ‖ Where
  the per-key menu button · frames 42–45
@ row `e27.scr128.test_note` ‖ String
  "Test runs the full check: if a key fails it, trading stops on every account until a restart
  passes the check, and trading on its account stays off until you turn it back on."
@ row `e27.scr128.policy.h3` ‖ String
  "How CandleViewer holds your keys"
@ row `e27.scr128.policy.encrypted` ‖ String
  "Each API secret is stored only encrypted, under a key of its own that is wrapped by a
  key-encryption key (KEK) kept outside the database."
@ row `e27.scr128.policy.write_only` ‖ Where
  policy 2 · frame 42 (**required: the write-only secret explanation**)
@ row `e27.scr128.policy.write_only` ‖ String
  "Write-only: CandleViewer uses a secret only to sign orders, and no one can see it again — not
  you, not an admin. If it is lost, create a new key at Bybit."
@ row `e27.scr128.policy.write_only` ‖ Status · source
  refined · CP-1 (panel form: “this secret to sign” → “a secret only to sign”; D02:609-610)
@ row `e27.scr128.policy.backups` ‖ String
  "Backups hold your keys only encrypted. Without the separate key-encryption key you keep
  offline, a restored backup cannot sign anything — on purpose."
@ row `e27.scr128.policy.allowlist` ‖ String
  "IP allowlists are set in Bybit's dashboard only; each key must allow exactly {egress_ip}.
  CandleViewer only checks it."
@ row `e27.scr128.policy.withdrawal` ‖ Id
  `e27.scr128.policy.withdrawal`
@ row `e27.scr128.policy.withdrawal` ‖ Where
  policy 5 · frame 42 (**required: the withdrawal verdict**)
@ row `e27.scr128.policy.withdrawal` ‖ String
  "No stored key can withdraw or transfer: such a key is refused, and every stored key is checked
  at start-up and every hour."
@ row `e27.scr128.policy.rotation` ‖ String
  "Keys are due for rotation every {n} days, set in this deployment's configuration; it can't be
  changed here. Overdue never stops trading."
@ row `e27.scr128.policy.kek` ‖ String
  "Rotating the key-encryption key is an operator runbook, not a control here."
@ row `e27.scr128.card.h2` ‖ String
  "Suspected compromise · {label} · key {key_id_masked} · {ENV}"
@ row `e27.scr128.card.lead` ‖ String
  "Do these in order. CandleViewer can stop its own trading on {label} and end the key here; only
  you can kill the key at Bybit."
@ row `e27.scr128.card.step2` ‖ String
  "Delete key {key_id_masked} in Bybit's dashboard now. Don't wait for step 3 or for a flatten:
  this is the only step that stops the key, and CandleViewer can't do it or confirm it."
@ row `e27.scr128.card.step3` ‖ String
  "Revoke it here — ends the key in CandleViewer."
@ row `e27.scr128.card.step4` ‖ String
  "Rotate the credential key (KEK), sign every session out and audit every order in the exposure
  window. The compromise runbook does these; there is no control here."
@ row `e27.scr128.card.step5` ‖ String
  "Replace the key — only after step 4."
@ row `e27.scr128.card.step5.button` ‖ Where
  step 5 control (SCR-126's key step) · frame 46
@ row `e27.scr128.card.step5.button` ‖ String
  "Add a new key…"
@ row `e27.scr128.card.marker` ‖ String
  "Recorded: the freeze, the revoke and the new key each in the audit log. Marking a compromise
  has no record of its own yet."
@ row `e27.scr128.card.refused.next` ‖ String
  "Delete the key at Bybit now (step 2) — that stops it."
@ row `e27.scr128.card.dead` ‖ String
  "Bybit no longer accepts key {key_id_masked}, so {label} can't be read or flattened here.
  Revoking leaves its {n} positions at Bybit, each with whatever stop-loss it carries — check each
  in Bybit's dashboard."
@ row `e27.scr128.card.containment` ‖ String
  "Trading is read-only for every account until the key is revoked here and a restart passes the
  check — that is the containment C-12.12 asks for."
@ row `e27.scr129.marker.revoke` ‖ String
  "Recorded in the audit log · API key revoked (api_key.revoke)"
@ row `e27.scr129.unknown.dead` ‖ String
  "{label}'s keys no longer work at Bybit, so its positions and orders can't be read or flattened.
  It can be disabled, leaving them at Bybit, each with whatever stop-loss it carries — check each
  in Bybit's dashboard. It can't be deleted."
@ row `e27.scr129.unknown.fixable` ‖ String
  "Bybit refuses {label}'s key from {egress_ip}. Fix it in Bybit's dashboard [Copy], then try
  again; until then nothing can be revoked, disabled or deleted."
@ row `e27.scr129.disable.history` ‖ String
  "History stays." · "You can enable it again." · "Its keys still work at Bybit."
@ row `e27.scr129.hint.typed` ‖ Status · source
  refined · E42-D03:620 `dlg.token` (“the username” → {label})
@ row `e27.scr129.delete.keys` ‖ Id
  `e27.scr129.delete.keys`
@ row `e27.scr129.delete.keys` ‖ String
  "{label}'s keys are revoked here and it stops trading."
@ row `e27.scr129.delete.bybit` ‖ String
  "Its keys still work at Bybit until you delete them there. Backups hold them only encrypted;
  without the KEK you keep offline they sign nothing."
@ row `e27.scr129.revoke.title` ‖ String
  "Revoke key {key_id_masked} on {label} · {ENV}"
@ row `e27.scr129.revoke.confirm` ‖ String
  "Revoke key {key_id_masked} here"
@ row `e27.scr129.revoke.last` ‖ Where
  rung 3, the last active key · frames 50, 51
@ row `e27.scr129.revoke.last` ‖ String
  "{label} has no other active key: it stops trading here."
@ row `e27.scr129.revoke.no_stop` ‖ String
  "{symbol} {side} {qty} has no stop-loss; once the key is gone nothing could add one. Add its
  stop first, or choose Flatten first."
@ row `e27.scr129.revoked.row` ‖ String
  "Revoked in CandleViewer. The key still works at Bybit until you delete it in Bybit's
  dashboard."
@ row `e27.scr129.revoked.subscribers` ‖ String
  "The account's API key was revoked."
@ row `e27.scr079.balances.caption` ‖ Id
  `e27.scr079.balances.caption`
@ row `e27.scr079.balances.caption` ‖ Where
  the balance block's freshness line (CMP-036 `freshness`) · frames 62–70
@ row `e27.scr079.balances.caption` ‖ String
  "Balances · as of {hh:mm:ss} UTC"
@ row `e27.scr079.balances.labels` ‖ Id
  `e27.scr079.balances.labels`
@ row `e27.scr079.balances.labels` ‖ Where
  the balance `dl` terms, in this order · frames 62–70
@ row `e27.scr079.balances.labels` ‖ String
  "Equity" · "Wallet balance" · "Available balance" · "Unrealised PnL" · "Initial-margin rate" ·
  "Realised PnL today" · "Maint.-margin rate"
@ row `e27.scr079.balances.units` ‖ Id
  `e27.scr079.balances.units`
@ row `e27.scr079.key.h3` ‖ Id
  `e27.scr079.key.h3`
@ row `e27.scr079.key.h3` ‖ String
  "Key and health"
@ row `e27.scr079.key.line` ‖ Id
  `e27.scr079.key.line`
@ row `e27.scr079.key.line` ‖ Where
  the Owner's key line: CMP-034 + the served status and both clocks (D7), from `listApiKeys`
  (`keys:read`) · frames 62–66
@ row `e27.scr079.key.line` ‖ String
  "API key {key_id_masked} · {status} · Rotation due {date} UTC · Bybit expiry: {date} UTC" · "API
  key {key_id_masked} · {status} · Rotation due {date} UTC · Bybit expiry: none"
@ row `e27.scr079.key.statements` ‖ Id
  `e27.scr079.key.statements`
@ row `e27.scr079.key.statements` ‖ Where
  the Owner's permission summary, a list of plain statements (`14:1750`; CMP-175 `key` facets) ·
  frames 62–66 (**required: the withdrawal verdict**)
@ row `e27.scr079.key.statements` ‖ String
  "Trade: yes." · "Withdrawal: off — verified {hh:mm} UTC." · "IP allowlist: matches."
@ row `e27.scr079.key.statements.other` ‖ Id
  `e27.scr079.key.statements.other`
@ row `e27.scr079.key.statements.other` ‖ Where
  the same list's other forms, one per CMP-175 state (“off” only for a fresh pass, `15:2046`; D4);
  the critical state is never a statement: its list item is the badge
  `e27.cmp175.withdrawal_detected` (§8) · frames 63–66
@ row `e27.scr079.key.statements.other` ‖ String
  "Withdrawal: not checked." · "Withdrawal: check overdue — last passed {hh:mm} UTC." · "IP
  allowlist: no match." · "IP allowlist: none set." · "IP allowlist: not checked."
@ row `e27.scr079.key.status` ‖ Id
  `e27.scr079.key.status`
@ row `e27.scr079.key.status` ‖ Where
  a Manager's and a Viewer's key line: `key_status` in words only (D15) · frames 67, 68
@ row `e27.scr079.key.status` ‖ String
  "API key: {status}"
@ row `e27.scr079.expiring.rotation` ‖ Where
  the Owner's key line, the policy clock (triangle) · frame 63
@ row `e27.scr079.ip_mismatch` ‖ String
  "CandleViewer accepts this key only if its IP allowlist holds exactly {egress_ip}. Set it in
  Bybit's dashboard [Copy], then test it again in Admin → Accounts. It can't be set from here."
@ row `e27.scr079.stale` ‖ Where
  CMP-239 chip replacing the “as of” line; the values stay at full contrast · frame 66
  (**required: the stale-balance badge**)
@ row `e27.scr079.stale.sizing` ‖ Where
  the chip's suffix, drawn only once G-11 serves a field · frame 66 (**required: the stale-balance
  badge**)
@ row `e27.scr079.announce.stale` ‖ String
  "Balances: stale since {hh:mm:ss} UTC"
@ row `e27.scr019.task.key` ‖ Id
  `e27.scr019.task.key`
@ row `e27.scr019.task.key` ‖ Where
  CMP-097 step, links to SCR-126's key step · frames 76–78
@ row `e27.scr019.task.key` ‖ String
  "Add its API key"
@ row `e27.scr019.done.register` ‖ Status · source
  new · D02:876-877 writes the key's done line only
@ row `e27.scr019.done.key` ‖ Id
  `e27.scr019.done.key`
@ row `e27.scr019.done.key` ‖ Where
  the step's done line, the Owner's: the key id and the time from `listApiKeys` (`keys:read`),
  never from the checklist's items (`22:21029-21047`) · frame 77
@ row `e27.scr019.done.key` ‖ String
  "API key added — key {key_id_masked} verified {hh:mm} UTC"
@ row `e27.scr019.done.key_other` ‖ Where
  the step's done line for any other role: no key facts (D15) · frame 77
@ row `e27.scr019.done.key_other` ‖ String
  "API key added"
@ prose
  **The contributed components' own strings** (CMP-034, BQ-8; CMP-175, BQ-5 — §2.1 holds the same
  words).
@ row `e27.cmp034.name` ‖ Where
  CMP-034 accessible name; the visible text is `...{last4}` only · every key id
@ row `e27.cmp034.description` ‖ Where
  CMP-034's description: one node per page in the DOM at mount, named by every CMP-034's
  `aria-describedby` · every key id (**required: the write-only secret explanation**)
@ row `e27.cmp034.description` ‖ String
  "Shows the last 4 characters of the key ID only. The full key and its secret are write-only and
  can't be shown anywhere in CandleViewer."
@ row `e27.cmp175.verified` ‖ Where
  CMP-175 pass (check) · §2.1
@ row `e27.cmp175.verified` ‖ String
  "Withdrawal OFF ✓ · verified {hh:mm} UTC"
@ row `e27.cmp175.trade_only` ‖ Where
  CMP-175 pass (check) · §2.1
@ row `e27.cmp175.read_only.stored` ‖ Where
  CMP-175 info, component level only (BQ-5 rider) · §2.1
@ row `e27.cmp175.withdrawal_detected` ‖ Id
  `e27.cmp175.withdrawal_detected`
@ row `e27.cmp175.withdrawal_detected` ‖ Where
  CMP-175 critical: octagon, bold, 2 px border; CMP-176's state slot, and the list item of
  SCR-079's statements as the badge (§8) · §2.1, frame 13 (**required: the withdrawal verdict**)
@ row `e27.cmp175.withdrawal_detected` ‖ String
  "BLOCKED — fund right found"
@ row `e27.cmp175.ip_missing` ‖ Where
  CMP-175 failed (octagon) · §2.1
@ row `e27.cmp175.ip_mismatch` ‖ Where
  CMP-175 failed (octagon); CMP-176's state slot · §2.1, frame 14 (**required: the IP-mismatch
  remediation**)
@ row `e27.cmp175.expiring` ‖ Where
  CMP-175 warning (triangle); CMP-176's state slot and SCR-079's key line · §2.1, frames 9, 63
@ row `e27.cmp175.expired` ‖ Where
  CMP-175 failed (octagon) · §2.1
@ row `e27.cmp175.not_checked` ‖ Where
  CMP-175 unknown (dash), never OFF · §2.1
@ row `e27.cmp175.not_checked` ‖ String
  "Withdrawal: not checked"
@ row `e27.cmp175.check_overdue` ‖ Where
  CMP-175 time warning (clock); CMP-176's state slot · §2.1, frame 2
@ row `e27.cmp175.allowlist_matches` ‖ Where
  CMP-175 pass (check); its header form "matches" on CMP-176's line 2 and in SCR-128's Allowlist
  cell (§2.1) · §2.1, frames 6–17, 42
@ row `e27.cmp175.allowlist_not_checked` ‖ Where
  CMP-175 unknown (dash), never a pass (AD-4); its header form "not checked" (§2.1) · §2.1
@ row `e27.shared.ask` ‖ Where
  the ask line before every `keys` press; on disable, delete and Enable… stamped “not yet served —
  G-8, #895 / #898” · frames 5, 19, 34, 49–59, 61
@ row `e27.shared.ask` ‖ String
  "You'll confirm with your password and a code."
@ row `e27.shared.kek_notice` ‖ Where
  the CMP-028 silent blocking notice's second sentence (BQ-9); its first is the reason
  `keys.kek_unavailable` (§12.2), the node every blocked key control's `aria-describedby` names ·
  frames 17, 29, 41, 45
@ row `e27.shared.kek_notice` ‖ String
  "Keys can't be added, tested or rotated until the KEK is back, and trading is off."
@ row `e27.shared.first_key_48h` ‖ String
  "Bybit's 48 h restriction applies to this account's first key; the time it lifts is not
  recorded. Demo trading is available meanwhile."
@ row `e27.shared.resend_unconfirmed` ‖ String
  "Couldn't confirm the result — reading the key's state…" · "Couldn't confirm the result —
  reading the account's state…"
§ spec ‖ 12.2 T2 reason keys
@ heading
  ### 12.2 T2 reason keys
@ prose
  A screen never writes its own reason (GATE G-T2.4): every gated control in §10.2 names one of
  these keys.
@ prose
  The ten E27 keys are PROPOSED, vocabulary owner E27, their registration beside E30-D02's state
  vocabulary routed to E09-D09 §3.1 by C-9 (`D02:1204`); each is one sentence of at most 60
  characters with a full stop, naming a capability, never data (`D09:402`).
@ prose
  Reason keys: 15 <!-- audit:numbers.reason_keys=15 -->, of them E27's 10 <!--
  audit:numbers.reason_keys_e27=10 -->.
@ head 1
  Key
@ row `keys.kek_unavailable` ‖ Key
  `keys.kek_unavailable`
@ row `keys.kek_unavailable` ‖ String
  "Off while the credential key is unavailable."
@ row `keys.kek_unavailable` ‖ Kind · source
  state, PROPOSED E27 (`D02:313`); known from `system` `secrets.kek_unavailable`; one notice, many
  pointers (BQ-9)
@ row `keys.kek_unavailable` ‖ Where
  Verify and save, Add a key…, Rotate key…, Test key… (frames 17, 29, 41, 45), and the CMP-028
  notice's first sentence; SCR-019's blocked step (frame 78)
@ row `keys.not_signable` ‖ Key
  `keys.not_signable`
@ row `keys.not_signable` ‖ String
  "Only an active or rotating key can be tested."
@ row `keys.not_signable` ‖ Kind · source
  state, PROPOSED E27 (`D02:314`); `ApiKey.status`
@ row `keys.not_signable` ‖ Where
  Test key… on a `pending`, `invalid` or `expired` key (frame 11)
@ row `keys.test_throttled` ‖ Key
  `keys.test_throttled`
@ row `keys.test_throttled` ‖ String
  "One test per key per minute; next at {hh:mm:ss} UTC."
@ row `keys.test_throttled` ‖ Where
  Test key… inside the minute after this client's own test (frame 11)
@ row `keys.compromise_path` ‖ Key
  `keys.compromise_path`
@ row `keys.compromise_path` ‖ String
  "A key that can move funds takes the compromise response."
@ row `keys.compromise_path` ‖ Where
  Rotate key… on a key whose check found a fund right (frame 13)
@ row `accounts.never_keyed` ‖ String
  "An account that never had a key can only be disabled."
@ row `accounts.never_keyed` ‖ Kind · source
  state, PROPOSED E27 (`D02:317`); an empty key list
@ row `accounts.key_rejected` ‖ String
  "This account's API key was rejected — trading is off."
@ row `accounts.no_key` ‖ String
  "No API key yet — trading is off for this account."
@ row `rbac.owner_only` ‖ Kind · source
  E09-D09 §3.1 (`D09:90`); {verb} "change account settings" for `accounts:write`, "manage API
  keys" for `keys:manage` (`D09:104-105`)
@ prose
  The other vocabularies' state keys the gated set consumes, never rewritten here (their strings
  may carry a time or a second sentence, GATE G-T2.4):
@ head 1
  Key
@ row `pending_key` ‖ String
  "API key pending — Bybit 48 h restriction, available after {date/time}. Demo trading is
  available meanwhile."
@ row `pending_key.untimed` ‖ String
  "API key pending — Bybit 48 h restriction; the time it lifts is not recorded. Demo trading is
  available meanwhile."
@ row `pending_key.untimed` ‖ Kind · source
  the memo's key (`MEMO:538`), routed to E30-D02 §14 by C-9 (`D02:1110`)
§ spec ‖ 12.3 Observability
@ prose
  Payloads carry fingerprints or ids, never key material (`TM:597`; `D02:476-477`, `D02:563`); an
  idempotency fingerprint leaves out `api_key` and `api_secret` or is a keyed hash (SR-E27-20,
  `TM:673`); and `account.detail_viewed` carries only the viewer's role (`D02:805`).
@ row `admin.key_form_opened` ‖ What the frame annotates
  the key step opened
§ spec ‖ 12.4 Validation against E27-D01
@ head 2
  Deck keys carrying it
@ row CP-1 — the secret can never be shown aga ‖ Probe (the fact)
  CP-1 — the secret can never be shown again
@ row CP-1 — the secret can never be shown aga ‖ Deck keys carrying it
  `e27.scr126.secret.help`, `e27.scr127.secret.help` (byte-equal to CP-1, also SCR-016 step 3's);
  `e27.scr126.edit.write_only`, `e27.scr128.policy.write_only`, `e27.scr126.saved`,
  `e27.cmp034.description`
@ row CP-1 — the secret can never be shown aga ‖ What the placement does
  the sentence is each secret field's description at mount; no control near it resembles a reveal
  (CMP-034 and CMP-201 write-only, BQ-8); no ask line suggests that a code unlocks anything, the
  misreading CP-1 names
@ row CP-5 — a key that can withdraw is never ‖ Probe (the fact)
  CP-5 — a key that can withdraw is never stored
@ row CP-5 — a key that can withdraw is never ‖ Deck keys carrying it
  `e27.scr126.refused.withdrawal` (byte-equal; SCR-016 step 3's too)
@ row CP-5 — a key that can withdraw is never ‖ What the placement does
  "Nothing was stored." leads the refusal and both fields clear at once; on a stored key the same
  fact is the BLOCKED row with the compromise response first, never Rotate
@ prose
  A scan of the deck for the two verbs finds each string that does not name its place itself, and
  the line read with it that does: the menu item "Revoke key…" and the revoke title open a dialog
  whose first consequence says "here" and "at Bybit" (`e27.scr129.revoke.not_last`,
  `e27.scr129.revoke.last`); the compromise card's "the revoke" lines sit under step 3, "Revoke it
  here — ends the key in CandleViewer."; "Not revoked: …" points at once to step 2
  (`e27.scr128.card.refused.next`); the delete confirms sit under the title "Delete {label} (keeps
  history) · {ENV}" and CD-5's lines, which end with "Its keys still work at Bybit until you
  delete them there."; "The account's API key was revoked." is the server's own text (`REV:108`),
  never rewritten.
@ prose
  The failed verdict's account clause now says "order entry on that key's account stays disabled
  by policy until it is turned back on", the words of E30-D02's
  `refusal.trading_disabled.account_disabled_by_policy` ("Order entry is disabled on {account} by
  policy", `E30-D02:437`).
@ prose
  The verdict says "that key's account", not "{account}", because the stored-key notice names no
  key and no account (`23:4270-4271`) — D03-Q1, to the orchestrator (§14).
@ prose
  **Material.** The boards of this spec, or the deck strings on cards, each card labelled with its
  key.
@ prose
  The compromise card (`e27.scr128.card.*`): "You suspect sub_001's key leaked.
@ prose
  What do you do first, second and third?" — understood if: freeze here, delete the key in Bybit's
  dashboard at once, then revoke it here (W3, `MEMO:510-513`).
@ prose
  Activation failed (`e27.scr126.activation_failed`): "Where is this key now?" — understood if:
  stored revoked here, and still working at Bybit.
§ spec ‖ 13. Storybook stories
@ row CMP-175 KeyPermissionBadge (`Atoms/KeyPe ‖ Component
  CMP-175 KeyPermissionBadge (`Atoms/KeyPermissionBadge`; §2.1)
@ row CMP-175 KeyPermissionBadge (`Atoms/KeyPe ‖ Stories
  Default (verified, trade, allowlist matches) · WithdrawalVerified · WithdrawalDetected
  (critical) · WithdrawalNotChecked · WithdrawalCheckOverdue · RightsTrade · RightsMissingScopes
  (an import refusal) · RightsReadOnly (stored; the owner's question, BQ-5) · AllowlistMatches ·
  AllowlistNoneSet · AllowlistNoMatch · AllowlistNotChecked · ExpiryExpiring · ExpiryExpired ·
  InlineForm · AggregateDated · AggregateOverdue · AggregateFailed · AggregateUnavailable ·
  AggregateReadFailed · AggregateNoKeys · AggregateLoading · VariantSet · MissingStateNeverOff ·
  ForcedColors
@ row CMP-034 MaskedValue (`Atoms/MaskedValue` ‖ Component
  CMP-034 MaskedValue (`Atoms/MaskedValue`; §2.3)
@ row CMP-034 MaskedValue (`Atoms/MaskedValue` ‖ Stories
  Default (on a row) · InDialog · InTableCell · WithDescription · NonMaskedValueRendersNothing ·
  ForcedColors; nothing else exists to show
@ row CMP-201 PasswordField, the `writeOnly` v ‖ Component
  CMP-201 PasswordField, the `writeOnly` variant (`Atoms/PasswordField`; §2.3)
@ row CMP-033 CopyButton (`Atoms/CopyButton`; ‖ Stories
  EgressIp (the key screens' one copy control)
§ spec ‖ 14. A, C, G and H rows, deviations and questions
@ row D03-A1 ‖ Row
  **`15`, twelve entries (Appendix A, table 1).** 62 copy-ready A-rows over CMP-175, CMP-176,
  CMP-034, CMP-028, CMP-035, CMP-044, CMP-066, CMP-178, CMP-201, CMP-203, CMP-011 and CMP-033,
  each the old line verbatim with its cite and then the new one; the table's other twelve rows are
  pointer lines (D03-A2), 74 rows in all <!-- audit:numbers.appendix_15=74 -->. CMP-044's and
  CMP-178's rows are re-read and re-based if E42-D03's boards PR lands its Appendix A first,
  CMP-066's against E42-D05's (GATE R6; D03-H8).
@ row D03-A3 ‖ Row
  **E05-D02's CMP-034 rules: the supersession** (BQ-8's owner rider, PROPOSED). Old (`E05F:448`):
  `- **G19 — CMP-034's security rules** (the ticket's Security note, written as design rules S1–S7
  in §7 CMP-034).` → new: ``- **G19 — CMP-034's security rules** (the ticket's Security note,
  written as design rules S1–S7 in §7 CMP-034). **Superseded by E27-D03 §2.3** (C-2.7, C-12.2): no
  screen displays a client-held key or secret, so CMP-034 is permanently masked; S4–S7 move to
  CMP-201's `writeOnly` variant, and S1–S3, the `autoHideMs` cap and G20 lapse with the display.``
  Old (`E05F:770`): `**Security design rules** (the ticket's Security note; flagged to the
  security engineer for E05-X02, §6 G19):` → new: ``**Security design rules** (the ticket's
  Security note; flagged to the security engineer for E05-X02, §6 G19; superseded by E27-D03 §2.3:
  S4–S7 bind CMP-201's `writeOnly` variant, and S1–S3 lapse):`` No board draws a reveal meanwhile
  (D03-C4).
@ row D03-A4 ‖ Row
  **E09-D09 §3.1: register E27's state vocabulary** (E27-D02's C-9, `D02:1204`). Old (`D09:85`, a
  fragment): ``(E30-D02 §14 — today's owner of `lockout` and `frozen`; E39-D01 is planned, not yet
  designed — and E17-D01 §7 for the feed states)`` → new: ``(E30-D02 §14 — today's owner of
  `lockout` and `frozen`; E39-D01 is planned, not yet designed — E17-D01 §7 for the feed states,
  and E27-D03 §12.2 for the ten accounts and key states, `keys.*` and `accounts.*`)``. Until it
  lands, each gated control's own `disabledReason` carries the string, E42-D03's interim
  (`E42-D03:602`).
@ row D03-A5 ‖ Row
  **E30-D02 §14: the two untimed 48 h strings** (E27-D02's C-9; OQ-5). Insert after `E30-D02:424`
  (the `pending_key` row), in its Key · String · Source · Where columns: (1) `pending_key.untimed`
  · "API key pending — Bybit 48 h restriction; the time it lifts is not recorded. Demo trading is
  available meanwhile." · new, the memo's key (`MEMO:538`) · SCR-019's blocked step until
  `unblock_at` records a time (frame 78); (2) `pending_key.first_key` (a name PROPOSED here) ·
  "Bybit's 48 h restriction applies to this account's first key; the time it lifts is not
  recorded. Demo trading is available meanwhile." · new, E27-D02's account-level wording
  (`D02:1110`) · an account that never held a key (frames 10 and 71). The timed `pending_key` row
  stays as it is.
@ row D03-C3 ‖ Row
  **A stored read-only key** (BQ-5's OWNER-LEVEL rider). The contract admits one: a key imported
  with `read_only: true` must report `readOnly: 1` (`22:2715-2718`; `ApiKey.read_only`,
  `22:16885`), while no `14` state, E27-D02 frame or story shows one and E27's flows import trade
  keys. **Decision:** CMP-175 specifies it at component level only, the info class with "Read only
  — can't trade" (§2.1; board 01), and no screen frame draws it until the owner rules whether E27
  accepts a read-only import.
@ row D03-C4 ‖ Row
  **E05-D02's time-limited display vs AC4.** E05-D02 respecified CMP-034 as a time-limited display
  of a value the client holds on SCR-126 and SCR-127 (S1–S7, `E05F:748-795`; G19, `E05F:448-453`);
  AC4, US-ACCT-002 (`11:344`), D13 (`D02:199`) and C-2.7 with C-12.2 rule out any reveal.
  **Decision (RULED to bind now, BQ-8):** CMP-034 is permanently masked, nothing displays a
  client-held secret, and S4–S7 move to CMP-201's `writeOnly` variant (§2.3; HD5). The
  supersession of E05-D02's text stays the owner's: D03-A3 is its copy-ready form, and no board
  draws a reveal meanwhile.
@ row D03-C5 ‖ Row
  **`15`'s grid rule vs E27-D02's plain table.** CMP-049 implies the grid pattern whenever a body
  column is interactive, an actions column included, and alternates canvas and raised rows
  (`15:528`, `15:531`); D22 keeps six records or fewer a plain table (`D02:208`, `D02:435-436`).
  **Decision:** SCR-125's list and SCR-128's key table are plain `<table>`s — header rows, `th
  scope="row"`, each record's buttons its Tab stops, no roving tabindex — with every record on
  `color.surface.raised`, so every pair is one §9 measures (§3.1, §6); CMP-049 should allow a
  plain table with an actions column up to a stated row count.
@ row D03-C6 ‖ Row
  **E42-D03's `strip.key_expiry` vs D7.** "Key for {account} expires in {n} d → Rotate"
  (`E42-D03:609`) names the rotation policy's clock with "expires", which D7 and AD-5 keep for
  Bybit's own expiry (`D02:193`; `MEMO:401`). **Decision:** on `/admin/accounts` the strip says
  `e27.shell.strip.rotation_due` and `e27.shell.strip.rotation_overdue` (§12.1; frames 9, 43).
  Copy-ready for its owner: `key_expiry` "Rotation due for {account} in {n} d → Rotate";
  `key_expiry_n` "{n} keys due for rotation within 30 days → Accounts and keys", one "1 key due
  for rotation …".
@ row D03-C7 ‖ Row
  **E42-D03's withdrawal strip and announcement vs C-12.12.** `strip.withdrawal` ends "has
  withdrawal permission — remove it on Bybit → Accounts and keys" and `announce.withdrawal` reads
  "Withdrawal permission found on a key. Remove it on Bybit." (`E42-D03:609`, `E42-D03:611`): both
  send the owner to edit the key's rights, where C-12.12 revokes the key at Bybit at once
  (`CON:824-825`; D9). **Decision:** the strip item reads `e27.shell.strip.withdrawal`,
  "Attention: {ENV} — a key on {label} can move funds → Start the compromise response" (frame 13),
  and CMP-092's blocking row is the one announcement (`15:935`; D03-C9). Copy-ready for its owner:
  `withdrawal` "Attention: a key on {account} can move funds → Start the compromise response";
  `announce.withdrawal` dropped.
@ row D03-C12 ‖ Row
  **CMP-015's skeleton token (resolved upstream).** At E27-D02's base CMP-015 named
  `color.surface.skeleton`, which is not a token; #4414 now binds its blocks to
  `color.surface.hover` on a raised host (`15:194`). **Decision:** frame 8's skeleton bars consume
  that binding as it stands, `color.surface.hover` on `color.surface.raised` and static under
  reduced motion; nothing is left to rule.
@ row D03-C13 ‖ Row
  **`14:2514`'s missing-allowlist warning.** SCR-125's checklist asks for "the warning state for a
  missing IP allowlist" (`14:2514`), while the contract refuses an empty whitelist in every
  environment and no setting turns the check off (`22:2722-2726`; AD-4, `MEMO:400`). **Decision:**
  a missing allowlist is CMP-175's failed state, "IP allowlist: none set", with the octagon (§2.1;
  frame 14); the warning class stays the clocks' and the health's.
@ row D03-C15 ‖ Row
  **E27-D02's undated "OFF".** D02's record, key table and drawer draw "Trade, Withdrawal OFF ✓"
  (`D02:349`, `D02:599`) and "Withdrawal: off." (`D02:785`) with no time, against its own D3,
  which "never says OFF without a time" (`D02:189`), and AD-3 (`MEMO:399`). **Decision:** the
  dated forms — "{key_id_masked} · Trade · Withdrawal OFF ✓ · verified {hh:mm} UTC" on SCR-125's
  record (`e27.scr125.row.key`), the same facet in SCR-128's Rights cell and "Withdrawal: off —
  verified {hh:mm} UTC." in SCR-079's statements (`e27.scr079.key.statements`), each time the
  key's `last_verified_at` (`22:16888`); and the check list's fresh pass, "OFF ✓ · verified
  {hh:mm} UTC" (`e27.checks.withdrawal.passed`, frames 3, 21 and 36), timed by the stored key's
  `last_verified_at` after a save and, on a refusal, whose `422` serves no time and stores
  nothing, by the response's `Date` header — the server's clock, never the client's (PROPOSED); a
  dated word wraps in its cell rather than lose its time (§3.1 block J, §6).
@ row D03-C16 ‖ Row
  **#4414's CMP-028, CMP-043 and CMP-044 lines** (E05-D02 slice 4, merged after E27-D02's base).
  (1) CMP-044's Tokens bind the destructive Confirm as a solid CMP-001 `danger`, whose label is
  under the 7.0 hc-text bar (§9 `c175-solid-danger`; the BQ-6 rider in §2.1); (2) its typed state
  keeps the Confirm natively `disabled`, where D03-C11 takes E42-D03's focusable validity form;
  (3) CMP-043's title is `type.ui.heading-sm`, where §2.4 binds `type.ui.heading-md`; (4) CMP-028
  gained `placement`, `live` and `edge`, and `live="off"` is half of `blocking`. **Decision:**
  Appendix A is re-based on #4414's text and changes only these four points: E27's destructive
  confirm on `color.status.danger.subtle` with its `color.status.danger.strong` hairline, the
  validity form, `type.ui.heading-md`, and `blocking` defined as `live="off"`, never dismissible
  and an `id`; every other #4414 addition is kept as written. The boards PR re-reads this row
  before it draws the confirm or the notice.
@ row D03-G1 ‖ Row
  **The egress IP before any check.** `EgressIp` is served only inside a verification result — a
  test this client ran, a `422` refusal or a rotation's (`22:2745-2749`, `22:16965`, `22:16995`) —
  and the `409 exposure_unknown` fix-key remedy carries no address (`22:15180-15188`). So the
  address CP-3 names on SCR-126's key step, SCR-127's stage 1, SCR-016's step 3, SCR-128's policy
  sentence 4, SCR-129's fixable remedy and SCR-079's mismatch has no source before a check, nor
  has SCR-125's details row (frame 14) before a Test this client ran, although the hourly
  self-check judged the stored key (no list field carries the address, `22:16873-16900`): each is
  a target state stamped "not yet served — D03-G1, #896", never an address another service echoes
  (BQ-15 item 7; HD14). PROPOSED: an Owner-only read of the configured egress IP, `GET
  /admin/security/egress-ip` returning `EgressIp`. Research PRs never edit `22`. Contract-first,
  the schema change lands in its own small PR, opened by the first implementation ticket that
  needs the field; the names here are PROPOSED (orchestrator ruling, 2026-10-21).
@ row D03-H1 ‖ Row
  **E27-D04 (#817), motion.** The validating state without a staged reveal (D18; AD-16), the stage
  changes and the 900 s countdown, which never changes colour and moves on the server's state
  (BQ-10), the compromise card's step changes and CMP-015's static skeletons, all under reduced
  motion; BQ-12's rider: checks appear one by one only when real backend progress drives them
  (§2.4).
@ row D03-H4 ‖ Row
  **E43-D02 (#1139), SCR-128's hardening and CMP-175's verdict set.** It extends CMP-175
  additively and never forks it — `verified-off` is `verified`, `verified-on` is `detected`,
  `unverifiable` is `not_checked` and `stale` is `overdue` (§2.1; BQ-5) — and draws SCR-128's
  provenance, drift naming, KEK id, last re-wrap, failure counts and per-UID rate budget (§6;
  O-H); its CMP-028 severity set keeps the `blocking` form (BQ-9); before it draws the KEK id or
  any other hardening state, it reviews each against C-12.2's metadata list — label, masked id,
  permissions, env (`SECR:15`) — since a response may expose only key metadata.
@ row D03-H5 ‖ Row
  **E09-D09's vocabulary owner.** D03-A4 registers the ten E27 state keys (C-9); the `rbac.*`
  strings stay E09-D09's, consumed verbatim (§12.2).
@ row D03-H7 ‖ Row
  **The token and contrast owner.** Register §9's 28 PROPOSED gated pairs in
  `tools/contrast/pairs.mjs`, `link-overlay` once E47-D03's retune lands (a design PR never edits
  `tools/`); the DS-3 alias `color.border.input` → `{color.text.tertiary}`; `color.text.link`'s
  missing high-contrast override (§9's reading 1: 6.66 <!--
  audit:pairs.row-link.high-contrast=6.66 --> in high contrast, under the 7:1 body-text aim of
  `05:130`); DS-6 with D03-C8; the skeleton binding of D03-C12.
@ row D03-H7 ‖ Owner
  the token owner · the E47-S06 palette owner
@ row D03-D1 ‖ Row
  Penpot, not Figma (the agent-delivery adaptation, owner decision 2026-09-25): page `E27-D03
  Accounts and key vault hi-fi` (§0).
@ row D03-Q1 ‖ Row
  **CD-2's account clause.** Default: the failed verdict says "that key's account", because the
  `accounts.key_selfcheck_failed` notice names no key and no account (`23:4270-4271`), while
  E30-D02's refusal names `{account}` after a press (`E30-D02:437`). Question: should the notice
  carry the account, so the verdict can name it (a `23` change)?
@ row D03-Q2 ‖ Row
  **The two added comprehension prompts** (§12.4, protocol item 6). Default: the protocol runs
  them — the compromise card's first three steps, and "Where is this key now?" after a failed
  activation — both PROPOSED and never run by an agent. Question: keep, change or drop them.
§ spec ‖ 15. Heuristic evaluation `(heuristic)` and the o
@ prose
  Severity: **critical** — a misreading moves money, strands a position or hides a fund right;
  **major** — a wrong step or a lost minute; **minor** — friction.
@ row 1 ‖ Finding (heuristic)
  N1, A-P: beside the ordinary warnings — rotation due, Bybit expiry, degraded, check overdue — a
  fund right found on a stored key must read as blocking at a glance, in greyscale too and in
  light, where the octagon and the triangle share one colour (§9) `(heuristic)`
@ row 2 ‖ Finding (heuristic)
  N1: "OFF" without a time, or for a key whose rights were never read, would overstate safety
  `(heuristic)`
@ row 2 ‖ Response
  "OFF" lives in one word only, always with its time (AD-3); the unread state is "Withdrawal: not
  checked" with the dash; a missing or unknown state renders "not checked" or nothing, never OFF
  (served enums with no default, HD1; the MissingStateNeverOff story)
@ row 3 ‖ Finding (heuristic)
  N2, the memo's H7: a "revoke" or a "delete" that does not say where it happens invites CP-4's
  predicted misreading, that a key revoked here is dead at Bybit (`MEMO:194`) `(heuristic)`
@ row 5 ‖ Finding (heuristic)
  N5, the ticket's Security notes: a masked key id drawn in a box, beside a toggle, under a timer
  or with a copy control would imply a reveal `(heuristic)`
@ row 5 ‖ Response
  CMP-034 is text only, `...{last4}` with its write-only description at mount; secrets go into
  CMP-201's write-only variant; the egress IP is the one copy control (BQ-8, RULED; §2.3; the
  tool's scans)
@ row 8 ‖ Response
  two clocks, two words, never one chip (D7; AD-5): "Rotation due" and "Rotation overdue" on
  CMP-011, "Bybit expiry" and "Expired at Bybit" on CMP-175; D03-C6 goes to E42-D03's owner
@ row 14 ‖ Finding (heuristic)
  N10: the hard facts — write-only secrets, KEK-separated backups, the allowlist set at Bybit —
  must be found where they matter `(heuristic)`
@ row 14 ‖ Response
  CP-1 under every secret field at mount, CP-2 in the policy and at the delete, CP-3 at the
  allowlist row and stage 1; SCR-128's policy in seven plain sentences (§6; §12.4)
@ prose
  (1) Metadata only: a key appears as its label, `...{last4}`, its rights, environment, status and
  dates, the Owner's alone (C-12.2; §2.3, §8).
@ prose
  (2) No key material, no plaintext and no reveal: CMP-034 is text only and CMP-201 write-only,
  and no frame draws more than the masked id (BQ-8; C-2.7).
@ prose
  (3) Withdrawal is never drawn as allowed: a fund right is CP-5's refusal on import and BLOCKED
  on a stored key, and the copy gate refuses any string that grants it (C-2.8; §16).
@ prose
  (5) T2 is E09-D09's, the view-as leg first (§10.1).
@ prose
  Answer about the frames only: #816 is public, so never paste or read a real key, secret, UID or
  IP.
@ prose
  Board 04 and its light twin 05: find the account whose key can move funds and say your first
  action; say whether any warning on the page could be taken for it (AC3: this item stands in for
  the fresh reviewer).
@ prose
  Boards 01 and 02, with their greyscale, deuteranopia and protanopia renders: name each CMP-175
  state from its word and glyph alone, and say which ones stop trading.
@ prose
  Board 06: add a key for demo-1 without a mouse; say where its IP allowlist is set, and what was
  stored after the withdrawal refusal.
@ prose
  Board 07: rotate sub_002's key; say what happens to open orders, until when the old key works
  here, and what is left to do at Bybit.
@ prose
  Board 08: revoke sub_002's last key with positions open, then disable and delete sub_002; say
  what happens to the positions each time, and whether anything closes them by itself.
@ prose
  Board 09: say what a Manager and a Viewer see of the key, and whether each locked control says
  why.
§ spec ‖ 16. Traceability and the audit tool's checks
@ prose
  HD1 and HD2 (CMP-175) → SCR-125, SCR-126, SCR-127, SCR-128, SCR-079 and SCR-016 · HD3 and HD4
  (CMP-176) → SCR-125 · HD5 (CMP-034, CMP-201) → every screen that names a key, and the write-only
  fields of SCR-126, SCR-127 and SCR-016 · HD6 (CMP-028) → SCR-125, SCR-126, SCR-127, SCR-128 and
  SCR-079's one notice · HD7 (CMP-035) → SCR-127 · HD8 (CMP-044) → SCR-129, SCR-126's edit (rung
  1) and SCR-128's card · HD9 (CMP-066) → SCR-126, SCR-127 and SCR-016 · HD10 (CMP-178) → SCR-125
  and SCR-079 · HD11 (the field well) → SCR-126, SCR-127, SCR-129 and SCR-016 · HD12, HD13 and
  HD15 → every screen · HD14 (the egress IP) → SCR-125, SCR-126, SCR-127, SCR-128, SCR-129,
  SCR-079 and SCR-016 · HD16 → SCR-128 · HD17 (the check list's warnings) → SCR-125's Test dialog,
  SCR-126, SCR-127 and SCR-016.
@ prose
  **Components → sections.** CMP-175 §2.1 · CMP-176 §2.2 and §3.2 · CMP-034, CMP-201 and CMP-033
  §2.3 · CMP-028, CMP-035, CMP-044, CMP-066 and CMP-178 §2.4 · CMP-011, CMP-203 and the
  compositions §2.5 · each of them in §13, Appendix A and the handoff file; the consumed
  components (CMP-087, CMP-088, CMP-092, CMP-041, CMP-049, CMP-050, CMP-079, CMP-019, CMP-046,
  CMP-239, CMP-006, CMP-005 and CMP-097) where §2.5 and the screen sections place them.
@ prose
  **Token bindings** (`tokens.unknown`, `tokens.dimmed`): every backticked token exists or its
  line marks it; `color.text.disabled` and `opacity.disabled` appear in a T2 or disabled row only
  negated.
@ prose
  **T2** (`t2.*`, `key.*`): the rule once, view-as first; every T2 frame citing "T2 per §10.1";
  every gated row naming CMP-079 and the `lock`; the not-T2 list whole; each reason one sentence
  of at most 60 characters with its full stop; `rbac.*` verbatim.
@ prose
  **The copy deck** (`deck.*`, `copy.banned`, `copy.utc`, `copy.off`, `withdraw`): ids keyed and
  unique; a status on every row; `unchanged` byte-equal to the memo and `consumed` verbatim in its
  source; no banned word; every clock time in UTC; a withdrawal "OFF" or "off" only beside its
  verified time (AD-3); no withdrawal or transfer right drawn as allowed.
@ prose
  **Appendix A** (`appx.*`, `reveal`): each Old cell found once in its entry — a moved line a
  WARN, gone or ambiguous a FAIL; CMP-044 and CMP-178 WARN while E42-D03's boards PR is open;
  pointer lines content-only; every Old and New cell read whole by item 12.
@ prose
  **Cites and scans** (`cite.*`, `scan`, `ids`, `forbidden`, `closing`, `placeholder`, `handoff`):
  every `KEY:line` resolves and a quoted fragment is still on its line; E27-D02's scans (no
  secret-shaped run, key ids `...` plus 4, addresses from RFC 5737 only, long numbers only the
  placeholder UIDs); every C-, CMP-, SCR- and US- id resolves; no private path or host, closing
  keyword or placeholder; no blank line in the handoff file.
@ prose
  **Frame rows** (standing rule A2, main-orchestrator 2026-10-25; `k1.masked`, `reveal`,
  `k3.withdraw`, `k4.consequence`, `k4.loading`, `k5.stepup`, `k6.lock`, `k7.reason`, `k8.viewas`,
  `k9.exit`, `k11.compromise`, `k12.env`, `k13.number`, `k2.field`, `k3.off`, `t2.viewas`,
  `pin.inflight`): each of the 78 <!-- audit:numbers.frame_rows=78 --> frame rows is read on its
  own, every clause of every cell.
@ prose
  K1: no control that shows or copies key material — a `[Show]`, a Show toggle, a `[Copy]` or a
  copy control whose nearest cue is a key or a secret field rather than the egress IP — no key id
  but `...` plus 4, no bare id (eight or more letters and digits, both present) and no
  plaintext-like value (a 16+ character run with two digits or short mixed-case segments, or a key
  value with a digit or an inner capital); K2: no reveal prop or state (item 12); K3: no
  withdrawal or transfer right drawn as allowed or as a toggle, switch or checkbox, and every
  withdrawal "OFF" a frame draws carries "verified" and its time in the same string or item
  (`k3.off`); K4 and K5: each destructive confirm (frames 5, 34, 49–51, 54–56, 58 and 59: 10 <!--
  audit:numbers.frames_destructive=10 --> in all) names its consequence key and the ask line
  `e27.shared.ask` in its Copy keys, both in §12, and its Hi-fi cell draws them — the
  consequence's §12 string with its placeholders filled, the ask line and, where its keys list
  `e27.scr129.typed`, the typed label (a row opening "As frame N" or "Frame N's dialog" inherits
  them from frame N); §7's confirms table states both, and no other frame draws a destructive
  confirm, and while the summary loads no frame, §2.4 cell or prose paragraph draws the confirm
  rendered, drawn, shown, visible or present, or with a gated word — disabled, `aria-disabled`,
  dimmed, greyed or grayed (out), inactive, inert, locked, held, hidden, unavailable, unusable,
  suppressed, no effect — before it ("a disabled confirm", "a greyed-out confirm") or after it
  anywhere in its sentence, across a semicolon, a dash, a cell and a parenthesis, so "it" carries
  the subject ("the confirm, visible but inactive"); a frame row, a §2.4 row or a prose paragraph
  (§16 and the revision line aside) that names the load is read whole, so a bare "A disabled
  confirm." on frame 53 fails, each sentence up to where it moves past the load ("after it", "once
  the summary has loaded", "when the summary arrives": the ready dialog's validity look, §10.3)
  (`k4.loading`); K6 to K8: each of the 20 <!-- audit:numbers.frames_t2=20 --> gated frames names
  the `lock` and CMP-079 RbacGate (§10.1's components) and a reason key a §10 or §12 table gives,
  `rbac.view_as` first wherever it appears and never put after another leg in the row's prose, no
  frame that is not gated draws a `lock` or CMP-079, a frame E27-D02's inventory or its name calls
  a view-as frame says "view-as leg first" in its class, and every §10.2 control the view-as
  session reaches as T2 `rbac.view_as` (its "Who sees what" row) lists the view-as leg first
  (`t2.viewas`); K9: no exit (Cancel, Close, Back, Esc with or without backticks) drawn gated, in
  a frame, a §2.4 cell, a prose paragraph (§16 and the revision line aside) or in §10.2, by the
  same gated words — after the exit in a parenthetical such as "(disabled)", after a verb, after a
  comma or a two-word appositive (", visible but inactive"), or carried by "it" or "which" later
  in the sentence, and before it ("a disabled [Cancel]", "an inactive CANCEL", "an unavailable
  Esc"; Cancel and Esc in any case there, Close and Back in Title or UPPER case or in brackets);
  K10: gate 2's word and glyph per state (`ac2.*`); K11: frame 46's steps, their keys and their
  deck strings in C-12.12's order (freeze, delete at Bybit, revoke, rotate the KEK, replace); K12:
  each of the 19 <!-- audit:numbers.frames_env=19 --> frames that names an environment, whose
  title or heading names an account, or that draws an "Attention:" strip string, keeps its badge —
  derived from the rows, not a fixed list; K13: the number before every marker is the marker's
  value, and every two-decimal contrast or ΔE76 value carries a marker; K14 and K15: gate 4's
  `inv.missing` and `inv.board`; and E42-D03's boards PR, in flight, is named by its branch only —
  a sha or a quote beside it fails (`pin.inflight`).
@ prose
  **The self-test** (`--self-test`; `--selftest` too): a passing spec built in memory from the
  base files refuses 37 <!-- audit:numbers.mutations=37 --> mutations, each by its own code, and a
  spec on disk with no FAIL meets every one that applies to it; then the standing rule's list, one
  mutation per K-item and a second (or more) where a K-item reads more than one element or form,
  three for the in-flight pin, and item 12's record forms of the text round 2 — each in the
  section the round named and again in another, in lower and title case, an allowed phrase copied
  to a new place, Appendix A's States cell, frame 69's view-as leg cut from its prose or swapped
  for the role leg, and three on the hand-off; and round 3's forms — "view the full key" and
  "toggle visibility" on §6's Key cell, §8's owner key row, §4.1's block H, §2.5's CMP-034 row and
  frame 36 (lower, title and upper case), "can withdraw" on §6's Rights row, §8's owner key row,
  §4.4's block D and frame 36, a bare id, `[Show]` and `[Copy]` on §4.4's block D result row and
  in §4's and §8's prose, a deck string cut to "off ✓" and "Off ✓" and §2.1's verified row cut to
  "off ✓", frame 69's class naming the role leg, and three on the hand-off's CMP-033 row (a bare
  32-hex id, "Can Withdraw", "view the full key"); and the re-check's gated words — "a disabled
  confirm", "a dimmed confirm", "the confirm, visible but inactive", "a greyed-out confirm" and
  each gated word before and after the confirm, on frame 53 and in §2.4's `consequenceState`, and
  "a disabled [Cancel]", "[Cancel], visible but inactive" and each gated word before and after the
  exit, on frame 53 and frame 11; and its ten forms as a sentence of their own, in lower, Title
  and UPPER case — the confirm's on frame 53, in §2.4's `consequenceState` and in §7's prose, the
  exit's ("a disabled [Cancel]", "an inactive Cancel", "an unavailable Esc", "Close (locked)",
  "the [Close], hidden", "a disabled cancel", "a dimmed [Back]") on frame 53, in §2.4's
  `consequenceState` and in §2.4's prose — 338 <!-- audit:numbers.k_mutations=338 --> in all, each
  run in memory on this spec (or the hand-off) as a plain run: rc 1 with exactly one distinct
  FAIL, its own code, among the gates of items 1–12 (item 13's pin refuses it too wherever it
  edits pinned text); then item 13's 94 <!-- audit:numbers.pin_mutations=94 --> pin mutations;
  restored, `--check` exits 0 and the spec on disk is byte-identical (its sha256 compared).
@ prose
  **The whole document** (the orchestrator's text round 2; `reveal`, `k1.masked`, `k2.field`,
  `k3.withdraw`, `k3.off`): every clause of every line of this spec and of the hand-off — every
  row of every table, every prose sentence, Appendix A's Old and New cells whole — is read
  case-insensitively, with no section list and no cue: a reveal word or affordance (any form of
  "reveal" or "unmask", CMP-034's old props and stories); K1's bare id (eight or more letters and
  digits, both present; a backticked 9- or 40-character git sha or a CamelCase story name passes
  only on a line that names no key) and an id after `...` that is not 4 characters; K2's show,
  view, display, copy, toggle or expose of a key or a secret, a visibility toggle, a show or hide
  control, and a bracketed `[Show]`, `[View]` or `[Copy]` whose nearest cue on the line is not the
  egress IP; K3's withdrawal or transfer right drawn as allowed, granted, as a control or in the
  modal form ("can withdraw", "may transfer", "able to withdraw"); and a withdrawal OFF, in any
  case, without its verified time in its own string or item — on a table row a withdrawal or
  transfer word in any cell ties the OFF to it, so a deck string cut to "off ✓" is read with its
  Where cell.
@ prose
  A clause that names a key or a secret field (or whose row's first cell or heading does) is also
  read for the plaintext-like run, a toggle and a bare "Copy".
@ prose
  The frame rows keep item 10's K1 and K3 and are read here for the reveal words, the dated OFF
  and the modal fund right.
@ prose
  **The security text, pinned default-deny** (the orchestrator's text round 3; `sec-pin`): a
  clause of this spec or of the hand-off (a heading, each table cell, each prose sentence, each
  fenced line) is security-bearing when it names a key, an API key or a key id, a secret, a
  credential, a passphrase, private, a withdrawal or transfer word, any fund, funds or money word
  (so a fund right phrased with one of them), a reveal or mask word in any form, plain or clear
  text or "in clear", a token, a password, a balance, "shown in full", CMP-034, CMP-175 or CMP-201
  by number or name, or a full, whole or raw id, case-insensitive, at a word boundary, plurals and
  hyphenations included; a clause that names the view-as leg is pinned too (§8's and §10.1's
  statements of the leg order).
@ prose
  Its self-test: each round-3 lens form twice (in a clause with no security word, and inside a
  pinned clause), the fund right and the clear text with no key word ("can move funds", "Can move
  funds", "funds can leave", "in clear") twice each too, §8's and §10.1's view-as leg cut, six
  placements on the hand-off, each refused by the pin alone, and twenty phrasings drawn at run
  time (seeded) — ten from a verb × object grid of key and secret words and ten from a grid of
  fund and clear-text phrasings with no key word — each placed in a table row and in a prose
  sentence and each refused.
@ prose
  r3 gave the frame rows the elements the K gates read where a row named them only by reference:
  the `lock` on frames 62–71 and 78, frame 66's `accounts.mode_locked` (`D02:828-830`), and the
  consequence and ask keys of frames 50, 51, 55, 56 and 59, as §12's Where column already places
  them.
§ spec ‖ 17. Summary for #816 (≤ 10 lines)
@ prose
  CMP-175 holds thirteen states in two scopes from served enums; only withdrawal-detected is
  BLOCKED, bold, bordered.
@ prose
  CMP-034 is permanently masked (BQ-8, RULED); secrets go into CMP-201's write-only variant; keys
  show `...{last4}`.
@ prose
  T2 is stated once, view-as first, with ten PROPOSED E27 reason keys; what is not T2 is listed.
§ spec ‖ Appendix A. The `15` and `14` edits, old → new
@ prose
  E42-D03's boards PR (`design/e42-d03-boards`) proposes edits to CMP-044's Props, A11y and
  Storybook lines and to CMP-178's Purpose, Props, A11y, Tokens and Storybook lines
  (`E42-D03:892-904`): whichever lands second re-reads its Old cells and re-bases (GATE R6), and
  the audit tool warns on both entries until then.
@ prose
  The rows cover twelve entries: the three contributions (CMP-175, CMP-176, CMP-034), the five
  extensions (CMP-028, CMP-035, CMP-044, CMP-066, CMP-178), CMP-201's write-only variant and the
  homes of §2.2, §2.3 and §2.5 (CMP-011, CMP-033, CMP-203).
@ row CMP-175 · Tier and Purpose (`15:2044`) ‖ Entry · field
  CMP-175 · Tier and Purpose (`15:2044`)
@ row CMP-175 · Tier and Purpose (`15:2044`) ‖ Old (verbatim)
  `- **Tier**: Atom (owner/admin, security-critical) · **Purpose**: shows the permission scope of
  an API key (trade/read/withdraw flags, IP-whitelist state) with withdrawal-off always visually
  confirmed.`
@ row CMP-175 · Tier and Purpose (`15:2044`) ‖ New
  ``- **Tier**: Atom (owner/admin, security-critical) · **Purpose**: one key's verified facts —
  its withdrawal verdict, its trade rights, its IP allowlist and its Bybit expiry — each a word
  with its class's glyph, never colour alone, and withdrawal-off always confirmed with its time;
  scope `key` places one facet in a row, a table cell or the account drawer, scope `aggregate` is
  the dated withdrawal verdict line under SCR-125's `h1`. E27-D03 owns the E27 state set; E43-D02
  extends it additively (its `verified-off`, `verified-on`, `unverifiable` and `stale` are
  `verified`, `detected`, `not_checked` and `overdue`).``
@ row CMP-175 · Props (`15:2045`) ‖ Entry · field
  CMP-175 · Props (`15:2045`)
@ row CMP-175 · Props (`15:2045`) ‖ Old (verbatim)
  ``- **Props**: `permissions: {trade:boolean; read:boolean; withdraw:boolean}` · `ipWhitelisted:
  boolean`.``
@ row CMP-175 · Props (`15:2045`) ‖ New
  ``- **Props**: `scope: "key"|"aggregate"` · `facet: "withdrawal"|"rights"|"allowlist"|"expiry"`
  (scope `key`) · `state` — withdrawal `"verified"|"detected"|"not_checked"|"overdue"`, rights
  `"trade"|"missing_scopes"|"read_only"`, allowlist
  `"matches"|"missing"|"mismatch"|"not_checked"`, expiry `"expiring"|"expired"` — served and
  required, with no default: a missing or unknown state renders the facet's "not checked" form
  (withdrawal, allowlist) or nothing (rights, expiry), never a pass · `verifiedAt?`
  (`last_verified_at`, UTC; required with `verified` and `overdue`) · `expiresInDays?` (with
  `expiring`) · `form?: "badge"|"inline"` (default `badge`; `detected` is always a badge) ·
  `verdict: "dated"|"overdue"|"failed"|"unavailable"|"read_failed"|"no_keys"|"loading"` (scope
  `aggregate`, from the `system` notices) · `count?` · `asOf?`. (Replaces `permissions` and
  `ipWhitelisted`: two booleans cannot say "not checked" or "overdue".)``
@ row CMP-175 · A11y (`15:2046`) ‖ Entry · field
  CMP-175 · A11y (`15:2046`)
@ row CMP-175 · A11y (`15:2046`) ‖ Old (verbatim)
  `- **A11y**: withdrawal-off state is rendered with an affirmative "Withdrawal: OFF ✓" text, not
  just the absence of a chip (absence-of-danger is not a safe visual pattern — must be explicit).`
@ row CMP-175 · A11y (`15:2046`) ‖ New
  ``- **A11y**: withdrawal-off is an affirmative, dated word, "Withdrawal OFF ✓ · verified {hh:mm}
  UTC", never the absence of a chip (absence-of-danger is not a safe visual pattern — must be
  explicit), and only for a key whose check passed inside the freshness window: a key whose rights
  were never read reads "Withdrawal: not checked". Every state is its own word with its class's
  glyph — check pass, octagon failed and critical, triangle warning, clock time warning, dash not
  checked, info a stored read-only key — the glyph `aria-hidden` beside the word; the critical
  word leads with "BLOCKED", in `font.weight.bold`, inside a 2 px border. Static text: not
  focusable, no live region (its host announces a transition once); in forced colours the fills
  drop and the word, the glyph and the critical border stay.``
@ row CMP-175 · Tokens (`15:2047`) ‖ Entry · field
  CMP-175 · Tokens (`15:2047`)
@ row CMP-175 · Tokens (`15:2047`) ‖ Old (verbatim)
  ``- **Tokens**: `color.status.success/danger`.``
@ row CMP-175 · Tokens (`15:2047`) ‖ New
  ``- **Tokens**: badge fill by class — pass `color.status.success.subtle`, failed and critical
  `color.status.danger.subtle`, warning and time warning `color.status.warning.subtle`, not
  checked `color.neutral.subtle`, stored read-only `color.status.info.subtle`; word
  `color.text.primary`, `type.ui.caption` in a badge and `type.ui.body` inline (CMP-011's and the
  row's); glyph `size.icon` in `color.status.success.strong`, `color.status.danger.strong`,
  `color.status.warning.strong` or `color.status.info.strong` (the dash `color.text.secondary`);
  the critical mark `font.weight.bold` and a `border.thick` border in
  `color.status.danger.strong`; `radius.badge`; min-height `size.control.compact` or
  `size.control.comfortable`; padding `space.inset.sm` or `space.inset.md`; gap `space.inset.xs`;
  the `inline` form drops the fill; the `aggregate` line `color.text.primary` with its time in
  `color.text.secondary`. No solid danger fill. (Replaces the success and danger names, which are
  not shipped tokens.)``
@ row CMP-175 · Storybook (`15:2048`) ‖ Entry · field
  CMP-175 · Storybook (`15:2048`)
@ row CMP-175 · Storybook (`15:2048`) ‖ Old (verbatim)
  `- **Storybook**: Default(SafeConfig), WithdrawEnabled(dangerVariant, shown only for
  legacy-audit display, never settable via UI), NoIpWhitelist(warning).`
@ row CMP-175 · Storybook (`15:2048`) ‖ New
  `- **Storybook**: Default (verified, trade, allowlist matches), WithdrawalVerified,
  WithdrawalDetected (critical; a stored key's check found a fund right; never settable via UI),
  WithdrawalNotChecked, WithdrawalCheckOverdue, RightsTrade, RightsMissingScopes (an import
  refusal), RightsReadOnly (a stored read-only key; the owner's question), AllowlistMatches,
  AllowlistNoneSet, AllowlistNoMatch, AllowlistNotChecked, ExpiryExpiring, ExpiryExpired,
  InlineForm, AggregateDated, AggregateOverdue, AggregateFailed, AggregateUnavailable,
  AggregateReadFailed, AggregateNoKeys, AggregateLoading, VariantSet (with greyscale, deuteranopia
  and protanopia snapshots), MissingStateNeverOff, ForcedColors.`
@ row CMP-175 · Tests (`15:2049`) ‖ Entry · field
  CMP-175 · Tests (`15:2049`)
@ row CMP-175 · Tests (`15:2049`) ‖ Old (verbatim)
  `- **Tests**: unit, visual, axe, "withdraw-enabled visual alarm" regression test (must never
  render neutrally).`
@ row CMP-175 · Tests (`15:2049`) ‖ New
  `- **Tests**: unit, visual, axe, "withdraw-enabled visual alarm" regression test (must never
  render neutrally); a missing or unknown state never renders OFF; the VariantSet snapshots in
  greyscale, deuteranopia and protanopia keep every word, glyph shape and the critical border.`
@ row CMP-175 · Hi-fi pointer (new; insert bef ‖ Entry · field
  CMP-175 · Hi-fi pointer (new; insert before `15:2050`)
@ row CMP-175 · Hi-fi pointer (new; insert bef ‖ New
  ``- **Hi-fi (E27-D03)**: [E27-D03.md](../design/E27/E27-D03.md) §2.1 (text-first, owner approval
  pending; boards 01 and 02 pending on page `E27-D03 Accounts and key vault hi-fi`) — the E27
  state set in its `key` and `aggregate` scopes and the critical mark; handoff checklist
  [E27-D03-handoff.md](../design/E27/E27-D03-handoff.md).``
@ row CMP-176 · Tier and Purpose (`15:2053`) ‖ Old (verbatim)
  `- **Tier**: Molecule (owner/admin) · **Purpose**: one row in the admin Accounts & Keys screen —
  account nickname, env, KeyPermissionBadge, rotate/revoke actions.`
@ row CMP-176 · Tier and Purpose (`15:2053`) ‖ New
  `- **Tier**: Molecule (owner/admin) · **Purpose**: one account in SCR-125's plain table, as two
  lines — line 1 the label, UID and environment (word and badge), the state (the worst that
  applies, one badge), the masked key id (CMP-034) with its rights and withdrawal facets (CMP-175)
  and one "Actions for {label}" menu; line 2 the allowlist facet (CMP-175), key age · rotation due
  and the health line (CMP-178 inline) — and a "Details for {label}" disclosure; its blocked state
  is the danger treatment and its two disabled forms keep full text contrast.`
@ row CMP-176 · Props (`15:2054`) ‖ New
  ``- **Props**: `account: AdminAccountRow` · `key?` (the key's served metadata; absent on a
  keyless account) · `facets` (the CMP-175 `key` states) · `state` (the worst that applies, in
  this precedence: `blocked`, then `key_refused` or `expired`, `allowlist_mismatch` or
  `allowlist_missing`, `down`, `off_by_policy`, `check_overdue` or `not_checked`,
  `rotation_overdue`, `degraded`, `rotation_due` or `bybit_expiry`, `no_key`, `disabled`, `ok`;
  from served fields only) · `health` (one `AccountHealth`, rendered by CMP-178 inline) · `menu:
  {id, label, ask?, disabledReason?, onSelect}[]` (the ask line and a gated item's reason as the
  item's second line) · `notice?: {kind:
  "blocked"|"disabled"|"off_by_policy"|"rotating"|"revoked", at?, until?}` (line 2's sentence) ·
  `primaryAction?` (the blocked row's "Start the compromise response", first in the row) ·
  `detailsOpen` · `onToggleDetails` · `details`. (Drops `onRotateKey`, `onRevoke` and
  `onEditProfile`: rotate and revoke are menu items, never inline destructive buttons.)``
@ row CMP-176 · Tokens (`15:2055`) ‖ Entry · field
  CMP-176 · Tokens (`15:2055`)
@ row CMP-176 · Tokens (`15:2055`) ‖ Old (verbatim)
  `- **Tokens**: inherits CMP-106 ProfileBadge + CMP-175.`
@ row CMP-176 · Tokens (`15:2055`) ‖ New
  ``- **Tokens**: inherits CMP-175, CMP-011, CMP-034 and CMP-178; row `color.surface.raised`
  (hover `color.surface.hover`); line 1 `type.ui.body` in `color.text.primary` (the label
  `type.ui.body-strong`); line 2 and the notice `color.text.secondary`; the UID, ages and dates
  `type.num.base`; rows divided by a `border.hairline` rule in `color.border.default`; focus
  `color.focus.ring` with `border.focus`; each line min-height `size.row.compact` or
  `size.row.comfortable`; cells `space.inset.sm` or `space.inset.md` inline, `space.inset.xs`
  block; blocked: the row `color.status.danger.subtle` with a 4 px (`space.1`) inline-start border
  in `color.status.danger.strong`; disabled: the same text tokens as any row, never
  `color.text.disabled` or `opacity.disabled`.``
@ row CMP-176 · Hi-fi pointer (new; insert bef ‖ New
  ``- **Hi-fi (E27-D03)**: [E27-D03.md](../design/E27/E27-D03.md) §2.2 (text-first, owner approval
  pending; board 03 pending on page `E27-D03 Accounts and key vault hi-fi`) — the two-line row,
  its state slot and precedence, the danger treatment and the two disabled forms; handoff
  checklist [E27-D03-handoff.md](../design/E27/E27-D03-handoff.md).``
@ row CMP-034 · Heading (`15:371`) ‖ Entry · field
  CMP-034 · Heading (`15:371`)
@ row CMP-034 · Heading (`15:371`) ‖ Old (verbatim)
  `### CMP-034 MaskedValue ("secret reveal")`
@ row CMP-034 · Heading (`15:371`) ‖ New
  `### CMP-034 MaskedValue (historical name "secret reveal": permanently masked, no reveal)`
@ row CMP-034 · Tier and Purpose (`15:373`) ‖ Entry · field
  CMP-034 · Tier and Purpose (`15:373`)
@ row CMP-034 · Tier and Purpose (`15:373`) ‖ Old (verbatim)
  `- **Tier**: Atom · **Purpose**: masked API key/secret display with reveal toggle (admin key
  screens).`
@ row CMP-034 · Tier and Purpose (`15:373`) ‖ New
  ``- **Tier**: Atom · **Purpose**: the server's masked key id, `...{last4}` from `key_id_masked`,
  as plain text wherever a key is named (the admin key screens, the account drawer, the setup
  checklist); it never receives a full value or a secret, so there is nothing to show and no
  control. Why no reveal exists: no API response or frontend bundle holds a secret (C-2.7); a
  response exposes only key metadata (C-12.2); "no reveal control anywhere in the app or API"
  (US-ACCT-002); only the last 4 characters of a key id are stored in clear; and a value that
  looks as if it could open is itself a misrepresentation (E27-D03 §2.3).``
@ row CMP-034 · Props (`15:374`) ‖ Entry · field
  CMP-034 · Props (`15:374`)
@ row CMP-034 · Props (`15:374`) ‖ Old (verbatim)
  ``- **Props**: `value: string` (a value the client holds in the current flow, never a stored
  secret: C-2.7) · `label: string` (what it is, e.g. "API secret"; names the group and the
  buttons) · `revealed?: boolean` (never `true` at mount) · `onToggleReveal` · `autoHideMs?:
  number` (default 10000, re-masks automatically) · `copyable?: boolean` (default `false`;
  CMP-033).``
@ row CMP-034 · Props (`15:374`) ‖ New
  ``- **Props**: `maskedId: string` (the served `key_id_masked`, `...` plus 4 characters; any
  other value renders nothing and warns without echoing it) · `label: string` (what it identifies,
  e.g. "API key"; names the group).``
@ row CMP-034 · States (`15:375`) ‖ Entry · field
  CMP-034 · States (`15:375`)
@ row CMP-034 · States (`15:375`) ‖ Old (verbatim)
  `- **States**: masked (default, at every mount: an 8-character mask whatever the value's
  length), revealed (only after a press of the toggle), expiring (the last 2 s, announced once),
  copied (CMP-033).`
@ row CMP-034 · States (`15:375`) ‖ New
  `- **States**: masked — its only state; with no key its host renders no CMP-034 (the row reads
  "No key — inactive").`
@ row CMP-034 · A11y (`15:376`) ‖ Entry · field
  CMP-034 · A11y (`15:376`)
@ row CMP-034 · A11y (`15:376`) ‖ Old (verbatim)
  ``- **A11y**: toggle is CMP-002 IconButton with label "Show {label}"/"Hide {label}" ("Show
  secret"/"Hide secret" when `label` is "secret"); auto-hide timer announced via polite live
  region ~2s before hiding ("Secret will hide in 2 seconds") satisfying WCAG 2.2.1 (no silent
  unannounced timing change). A route change, window blur, the idle lock and sign-out re-mask;
  while masked the DOM holds the mask only, never the value; copy logs nothing and the live region
  never holds the value; the value never enters browser storage
  (`docs/design/E05/E05-D02-form-controls.md` §7, rules S1–S7; flagged for E05-X02; recovery codes
  are CMP-206's).``
@ row CMP-034 · A11y (`15:376`) ‖ New
  ``- **A11y**: `role="group"` named by `label`; the `...` is `aria-hidden` behind a visually
  hidden "ending in", so it reads "API key, ending in a1b2"; one description node per page, in the
  DOM at mount, which every CMP-034 on the page names by `aria-describedby` (one node, many
  pointers), says the value is write-only and can't be shown (the copy deck's string); not
  focusable, no control, no timer, no live region; no attribute, `title`, data attribute,
  accessible name or hidden node holds more than the masked id.``
@ row CMP-034 · Tokens (`15:377`) ‖ Entry · field
  CMP-034 · Tokens (`15:377`)
@ row CMP-034 · Tokens (`15:377`) ‖ Old (verbatim)
  ``- **Tokens**: box `color.surface.raised` with a 1 px `color.border.default` hairline,
  `radius.control`, `size.control.height`, `space.inset.sm`; value `type.num.base` +
  `color.text.primary`; mask `color.text.secondary`; countdown (CMP-035) `type.ui.caption` +
  `color.text.tertiary`; buttons `space.inset.xs` apart. (Replaces `font.mono`.)``
@ row CMP-034 · Tokens (`15:377`) ‖ New
  ``- **Tokens**: text only, no box: `type.num.base` in `color.text.primary` on its host's surface
  (`color.surface.raised` in a row, `color.surface.overlay` in a dialog or the drawer); the
  description visually hidden. (Replaces the box, the toggle and the countdown; the mono face
  comes from `type.num.base`.)``
@ row CMP-034 · Storybook (`15:378`) ‖ Entry · field
  CMP-034 · Storybook (`15:378`)
@ row CMP-034 · Storybook (`15:378`) ‖ Old (verbatim)
  `- **Storybook**: Masked, Revealed, AutoHideCountdown, Copyable.`
@ row CMP-034 · Storybook (`15:378`) ‖ New
  `- **Storybook**: Default (on a row), InDialog, InTableCell, WithDescription,
  NonMaskedValueRendersNothing, ForcedColors.`
@ row CMP-034 · Tests (`15:379`) ‖ Entry · field
  CMP-034 · Tests (`15:379`)
@ row CMP-034 · Tests (`15:379`) ‖ New
  ``- **Tests**: unit (only `...` plus 4 characters renders), visual, axe; a regression that the
  DOM never holds more than the masked id.``
@ row CMP-034 · Hi-fi pointer (new; insert bef ‖ Entry · field
  CMP-034 · Hi-fi pointer (new; insert before `15:380`)
@ row CMP-034 · Hi-fi pointer (new; insert bef ‖ New
  ``- **Hi-fi (E27-D03)**: [E27-D03.md](../design/E27/E27-D03.md) §2.3 (text-first, owner approval
  pending; boards 01 and 02 pending on page `E27-D03 Accounts and key vault hi-fi`) — permanently
  masked, the old name annotated, the rationale recorded; handoff checklist
  [E27-D03-handoff.md](../design/E27/E27-D03-handoff.md).``
@ row CMP-201 · Tier and Purpose (`15:2413`) ‖ Entry · field
  CMP-201 · Tier and Purpose (`15:2413`)
@ row CMP-201 · Tier and Purpose (`15:2413`) ‖ Old (verbatim)
  ``- **Tier**: Atom · **Purpose**: password input with a reveal toggle, caps-lock warning and
  `autocomplete` wiring.``
@ row CMP-201 · Tier and Purpose (`15:2413`) ‖ New
  ``- **Tier**: Atom · **Purpose**: password input with a reveal toggle, caps-lock warning and
  `autocomplete` wiring; its `writeOnly` variant takes an API key or secret (SCR-126, SCR-127
  stage 2, SCR-016 step 3) with no toggle at all.``
@ row CMP-201 · Props (`15:2414`) ‖ Entry · field
  CMP-201 · Props (`15:2414`)
@ row CMP-201 · Props (`15:2414`) ‖ Old (verbatim)
  ``- **Props**: `value` · `onChange` · `autoComplete: "current-password"|"new-password"` ·
  `showReveal?: boolean = true` · `error?: string`.``
@ row CMP-201 · Props (`15:2414`) ‖ New
  ``- **Props**: `value` · `onChange` · `autoComplete: "current-password"|"new-password"|"off"` ·
  `showReveal?: boolean = true` · `error?: string` · `writeOnly?: boolean` (with `true`:
  `showReveal` is `false` and cannot be passed, `autoComplete` is `"off"`, `description` is
  required) · `description?` (the write-only sentence).``
@ row CMP-201 · Variants (new; insert before ` ‖ Entry · field
  CMP-201 · Variants (new; insert before `15:2415`)
@ row CMP-201 · Variants (new; insert before ` ‖ New
  ``- **Variants**: default; `writeOnly` — `type=password` always and never re-filled; paste
  allowed; read-only, never `disabled`, while its form's action is busy; cleared on Cancel, on
  leaving the page, on a cancelled, expired or third-failed step-up, on the idle lock (SCR-005),
  at absolute session expiry and on sign-out, on a refusal that sends the key away (a withdrawal
  or transfer right, the environment, the UID, the expiry) and after a successful save; the value
  lives only in the input's value — never an attribute, a `title`, a data attribute, the
  accessible name, a hidden node, a log, an analytics event, an audit record, an error report,
  browser storage, a URL, an autofill store or the undo history — and leaves state on unmount
  (E05-D02's rules S4–S7, moved here).``
@ row CMP-201 · A11y (`15:2415`) ‖ Entry · field
  CMP-201 · A11y (`15:2415`)
@ row CMP-201 · A11y (`15:2415`) ‖ Old (verbatim)
  ``- **A11y**: reveal is a real `<button aria-pressed>` labelled "Show password"/"Hide password";
  caps-lock warning is a polite live region; never suppresses paste.``
@ row CMP-201 · A11y (`15:2415`) ‖ New
  ``- **A11y**: reveal is a real `<button aria-pressed>` labelled "Show password"/"Hide password";
  caps-lock warning is a polite live region; never suppresses paste. With `writeOnly` no toggle
  exists in the DOM, and the `description` ("value is write-only", or the write-only secret
  sentence) is in the DOM at mount, linked by `aria-describedby`; a format error shows inline on
  press.``
@ row CMP-201 · Storybook (`15:2417`) ‖ Entry · field
  CMP-201 · Storybook (`15:2417`)
@ row CMP-201 · Storybook (`15:2417`) ‖ Old (verbatim)
  `- **Storybook**: Default, Revealed, CapsLockOn, WithError.`
@ row CMP-201 · Storybook (`15:2417`) ‖ New
  `- **Storybook**: Default, Revealed, CapsLockOn, WithError, WriteOnlyKey, WriteOnlySecret,
  WriteOnlyFormatError, WriteOnlyReadOnlyWhileVerifying, WriteOnlyClearedAfterRefusal,
  WriteOnlyPaste.`
@ row CMP-201 · Tests (`15:2418`) ‖ Entry · field
  CMP-201 · Tests (`15:2418`)
@ row CMP-201 · Tests (`15:2418`) ‖ Old (verbatim)
  `- **Tests**: unit, visual, axe, interaction (reveal toggle, paste allowed).`
@ row CMP-201 · Tests (`15:2418`) ‖ New
  ``- **Tests**: unit, visual, axe, interaction (reveal toggle, paste allowed); with `writeOnly`:
  no toggle rendered and `showReveal` refused by the type, cleared on leave, never in storage or
  the accessible name.``
@ row CMP-201 · Hi-fi pointer (new; insert bef ‖ Entry · field
  CMP-201 · Hi-fi pointer (new; insert before `15:2419`)
@ row CMP-201 · Hi-fi pointer (new; insert bef ‖ New
  ``- **Hi-fi (E27-D03)**: [E27-D03.md](../design/E27/E27-D03.md) §2.3 (text-first, owner approval
  pending; board 03 pending on page `E27-D03 Accounts and key vault hi-fi`) — the `writeOnly`
  variant for API keys and secrets.``
@ row CMP-028 · Tokens (`15:318`) ‖ Entry · field
  CMP-028 · Tokens (`15:318`)
@ row CMP-028 · Hi-fi pointer (new; insert bef ‖ New
  ``- **Hi-fi (E27-D03)**: [E27-D03.md](../design/E27/E27-D03.md) §2.4 (text-first, owner approval
  pending; board 03 pending on page `E27-D03 Accounts and key vault hi-fi`) — the blocking danger
  form: the KEK-unavailable notice.``
@ row CMP-035 · Tier and Purpose (`15:383`) ‖ Old (verbatim)
  `- **Tier**: Atom · **Purpose**: bar-close countdown, admin re-auth token expiry countdown,
  secret auto-hide.`
@ row CMP-035 · Tier and Purpose (`15:383`) ‖ New
  `- **Tier**: Atom · **Purpose**: bar-close countdown, admin re-auth token expiry countdown, the
  key-rotation overlap (SCR-127 stage 4: the served end time first, the time left second).`
@ row CMP-035 · Tokens (`15:386`) ‖ Entry · field
  CMP-035 · Tokens (`15:386`)
@ row CMP-035 · Tokens (`15:386`) ‖ Old (verbatim)
  ``- **Tokens**: `font.mono`, `color.text.warning` (under threshold).``
@ row CMP-035 · Tokens (`15:386`) ‖ New
  ``- **Tokens**: `type.num.base`; the time left `color.text.secondary`, the absolute time
  `color.text.primary`; under a threshold the colour does not change (a host that marks one adds
  the CMP-019 clock glyph in `color.status.warning.strong`). (Replaces the mono and warning-text
  names, which are not shipped tokens.)``
@ row CMP-035 · Hi-fi pointer (new; insert bef ‖ New
  ``- **Hi-fi (E27-D03)**: [E27-D03.md](../design/E27/E27-D03.md) §2.4 (text-first, owner approval
  pending; boards 03 and 07 pending on page `E27-D03 Accounts and key vault hi-fi`) — the 900 s
  rotation overlap: the served end first, server-corrected time, no fault colour.``
@ row CMP-044 · Tier and Purpose (`15:475`) ‖ Old (verbatim)
  `- **Tier**: Molecule (composed on CMP-043) · **Purpose**: destructive/irreversible action gate
  (flatten all, cancel all, Demo→Live switch, delete API key).`
@ row CMP-044 · Tier and Purpose (`15:475`) ‖ New
  `- **Tier**: Molecule (composed on CMP-043) · **Purpose**: destructive/irreversible action gate
  (flatten all, cancel all, Demo→Live switch, revoke an API key here, disable or delete an
  exchange account); a key is revoked in CandleViewer, never deleted at Bybit.`
@ row CMP-044 · Tokens (`15:479`) ‖ Entry · field
  CMP-044 · Tokens (`15:479`)
@ row CMP-044 · Hi-fi pointer (new; insert bef ‖ New
  ``- **Hi-fi (E27-D03)**: [E27-D03.md](../design/E27/E27-D03.md) §2.4 (text-first, owner approval
  pending; boards 03 and 08 pending on page `E27-D03 Accounts and key vault hi-fi`) — the rungs as
  E27 uses them: the consequence summary before any confirm, the environment in the title, `Enter`
  never confirming the typed label.``
@ row CMP-066 · Tier and Purpose (`15:683`) ‖ New
  `- **Tier**: Molecule · **Purpose**: onboarding/setup wizards (first-run account connect,
  rule-creation wizard, the add-account steps of SCR-126, the key-rotation stages of SCR-127).`
@ row CMP-066 · Tokens (`15:686`) ‖ Entry · field
  CMP-066 · Tokens (`15:686`)
@ row CMP-066 · Tokens (`15:686`) ‖ Old (verbatim)
  ``- **Tokens**: `color.status.*`.``
@ row CMP-066 · Tokens (`15:686`) ‖ New
  ``- **Tokens**: `done` `color.status.success.strong`; `error` `color.status.danger.strong`;
  `current` a `color.action.primary.default` marker, its numeral `color.text.on-action`, its label
  `type.ui.body-strong` in `color.text.primary`; `todo` a 1 px outline in `color.text.tertiary`,
  its numeral and label `color.text.secondary`; connectors `border.hairline` in
  `color.border.default` (decorative); `meta` `type.num.base` in `color.text.secondary`; markers
  `size.control.compact`; gaps `space.inset.sm` or `space.inset.md`. (Replaces the bare status
  family.)``
@ row CMP-066 · Hi-fi pointer (new; insert bef ‖ New
  ``- **Hi-fi (E27-D03)**: [E27-D03.md](../design/E27/E27-D03.md) §2.4 (text-first, owner approval
  pending; boards 03 and 07 pending on page `E27-D03 Accounts and key vault hi-fi`) — one stepper
  in `list` and `nav` forms, refused never failed, real elapsed time.``
@ row CMP-178 · Tier and Purpose (`15:2070`) ‖ New
  ``- **Tier**: Molecule (owner/admin) · **Purpose**: one metric tile on the admin Health screen —
  ingestion lag, WS state, DB status, engine FPS, each with threshold-based tone. Its `inline`
  variant is one account's connection health as text inside a CMP-176 row or the account drawer's
  key block: the word, its glyph and the heartbeat age, with no tile chrome, no sparkline and no
  link.``
@ row CMP-178 · A11y (new; insert before `15:2 ‖ New
  ``- **A11y**: the `inline` variant is plain text in its host's cell, with no region, heading or
  link; its word always carries its glyph (check healthy, triangle degraded, octagon down); no
  live region of its own: the shell announces a transition once (down assertive, degraded and
  recovery polite), never a refresh, and the age never ticks.``
@ row CMP-178 · Tokens (`15:2072`) ‖ Entry · field
  CMP-178 · Tokens (`15:2072`)
@ row CMP-178 · Tokens (`15:2072`) ‖ Old (verbatim)
  `- **Tokens**: inherits CMP-050 Card + CMP-024 Sparkline.`
@ row CMP-178 · Tokens (`15:2072`) ‖ New
  ``- **Tokens**: inherits CMP-050 Card + CMP-024 Sparkline; the `inline` variant: the word
  `type.ui.body` in `color.text.primary`, the age `type.num.base` in `color.text.secondary`, the
  glyph `size.icon` in `color.status.success.strong`, `color.status.warning.strong` or
  `color.status.danger.strong`, `space.inset.xs` between them.``
@ row CMP-178 · Hi-fi pointer (new; insert bef ‖ New
  ``- **Hi-fi (E27-D03)**: [E27-D03.md](../design/E27/E27-D03.md) §2.4 (text-first, owner approval
  pending; board 03 pending on page `E27-D03 Accounts and key vault hi-fi`) — the `inline` variant
  for per-key health.``
@ row CMP-011 · Hi-fi pointer (new; insert bef ‖ New
  ``- **Hi-fi (E27-D03)**: [E27-D03.md](../design/E27/E27-D03.md) §2.2 (text-first, owner approval
  pending; boards 01 and 02 pending on page `E27-D03 Accounts and key vault hi-fi`) — the
  account-row state chips: "OK" neutral with the check, the clock for the overdue states.``
@ row CMP-203 · Tier and Purpose (`15:2431`) ‖ New
  `- **Tier**: Atom · **Purpose**: live-validating list of policy requirements (length, character
  classes, not-reused) for SCR-004; and the key gate's check list (SCR-126, SCR-127 stage 3, the
  Test dialog, SCR-016 step 3): one row per check, each passed, failed or not checked in words, a
  pass that carries a served warning on the triangle.`
@ row CMP-203 · Props (`15:2432`) ‖ New
  ``- **Props**: `items: {label: string; met: boolean}[]` (SCR-004) or `checks: {label: string;
  outcome: "passed"|"failed"|"not_checked"; warning?: "key_expiring_soon"|"clock_skew"; detail?:
  string}[]` (the key gate; `detail` the rule's fixed words or the passed value, never exchange
  text; `warning` the served warning a passed check carries) · `live?: boolean` (default `true`;
  `false` for the key gate, whose host announces the verdict once).``
@ row CMP-203 · Tokens (`15:2434`) ‖ Entry · field
  CMP-203 · Tokens (`15:2434`)
@ row CMP-203 · Tokens (`15:2434`) ‖ Old (verbatim)
  ``- **Tokens**: `color.status.success`, `color.text.muted`.``
@ row CMP-203 · Tokens (`15:2434`) ‖ New
  ``- **Tokens**: met or passed `color.status.success.strong` (the check), passed with a warning
  `color.status.warning.strong` (the triangle), failed `color.status.danger.strong` (the octagon),
  not met or not checked `color.text.secondary` (the dash); words `color.text.primary`, `detail`
  `color.text.secondary`; `type.ui.body`, `size.icon`. (Replaces the bare success and muted names,
  which are not shipped tokens.)``
@ row CMP-203 · Hi-fi pointer (new; insert bef ‖ New
  ``- **Hi-fi (E27-D03)**: [E27-D03.md](../design/E27/E27-D03.md) §2.5 (text-first, owner approval
  pending; board 03 pending on page `E27-D03 Accounts and key vault hi-fi`) — the key gate's check
  list: passed, failed and not checked in words.``
@ row CMP-033 · Tier and Purpose (`15:363`) ‖ Old (verbatim)
  `- **Tier**: Atom · **Purpose**: copy-to-clipboard affordance (API key display, audit record id,
  order id).`
@ row CMP-033 · Tier and Purpose (`15:363`) ‖ New
  `- **Tier**: Atom · **Purpose**: copy-to-clipboard affordance (the deployment's egress IP, the
  only value the key screens copy; audit record id; order id); never a key id, a UID or a secret.`
@ row CMP-033 · Storybook (`15:368`) ‖ New
  `- **Storybook**: Default, CopiedState, EgressIp (the key screens' one copy control).`
@ row CMP-033 · Hi-fi pointer (new; insert bef ‖ New
  ``- **Hi-fi (E27-D03)**: [E27-D03.md](../design/E27/E27-D03.md) §2.3 (text-first, owner approval
  pending; board 06 pending on page `E27-D03 Accounts and key vault hi-fi`) — the egress IP as the
  key screens' only copy.``
@ row SCR-016 · insert before `14:441` ‖ New
  ``- **Hi-fi (E27-D03, step 3):** [E27-D03.md](../design/E27/E27-D03.md) §4 (text-first, owner
  approval pending; insets on board 06, pending on page `E27-D03 Accounts and key vault hi-fi`) —
  the account step in colour: CMP-201's write-only fields with the write-only sentence at mount,
  the verdict as a result row the server fills, loading, valid, invalid and skipped.``
@ row SCR-079 · insert before `14:1756` ‖ New
  ``- **Hi-fi (E27-D03):** [E27-D03.md](../design/E27/E27-D03.md) §8 (text-first, owner approval
  pending; board 09 pending on page `E27-D03 Accounts and key vault hi-fi`) — the drawer in
  compact density with one comfortable inset, per role and in view-as, the stale balance at full
  contrast, the Owner's key block in CMP-175's words.``
@ row SCR-125 · insert before `14:2517` ‖ New
  ``- **Hi-fi (E27-D03):** [E27-D03.md](../design/E27/E27-D03.md) §3 (text-first, owner approval
  pending; boards 04 and 05 pending on page `E27-D03 Accounts and key vault hi-fi`) — CMP-176's
  two-line rows grouped LIVE and DEMO, the dated verdict (CMP-175 `aggregate`), withdrawal
  detected as the danger treatment beside the warnings, the KEK notice (CMP-028), in dark and
  light.``
@ row SCR-126 · insert before `14:2545` ‖ New
  ``- **Hi-fi (E27-D03):** [E27-D03.md](../design/E27/E27-D03.md) §4 (text-first, owner approval
  pending; board 06 pending on page `E27-D03 Accounts and key vault hi-fi`) — CMP-201's write-only
  fields, the allowlist row with the one copy control, the three-outcome check list (CMP-203), the
  result panel, the ask before the press and every refusal.``
@ row SCR-127 · insert before `14:2558` ‖ New
  ``- **Hi-fi (E27-D03):** [E27-D03.md](../design/E27/E27-D03.md) §5 (text-first, owner approval
  pending; board 07 pending on page `E27-D03 Accounts and key vault hi-fi`) — the five stages on
  CMP-066 with their real elapsed time, the 900 s overlap on CMP-035 with the served end first,
  the refused new key and the delete-at-Bybit note.``
@ row SCR-128 · insert before `14:2570` ‖ New
  ``- **Hi-fi (E27-D03):** [E27-D03.md](../design/E27/E27-D03.md) §6 (text-first, owner approval
  pending; boards 04 and 05 pending on page `E27-D03 Accounts and key vault hi-fi`) — the key
  table (its compact density legible at 125 %), the secrets-at-rest policy, the overdue state and
  the ordered compromise card; E43-D02 (#1139) adds the hardening states.``
@ row SCR-129 · insert before `14:2582` ‖ New
  ``- **Hi-fi (E27-D03):** [E27-D03.md](../design/E27/E27-D03.md) §7 (text-first, owner approval
  pending; board 08 pending on page `E27-D03 Accounts and key vault hi-fi`) — revoke, disable and
  delete on CMP-044's rungs: the consequence summary before any confirm, two choices with none
  selected, the typed label and the Bybit line.``
§ hand-off ‖ E27-D03 — Per-component handoff checklist (`16`
@ heading
  # E27-D03 — Per-component handoff checklist (`16` §11.4; the contracts the accounts and
  key-vault hi-fi changes)
@ prose
  Three checklists for the contributions (CMP-175 KeyPermissionBadge, CMP-176 AccountKeyRow,
  CMP-034 MaskedValue) with every line of the `16` §11.4 block kept; one delta row per extended
  entry (CMP-028, CMP-035, CMP-044, CMP-066, CMP-178, CMP-201, CMP-203, CMP-011 and CMP-033);
  Tables 1–5, the Density table and the Essential-exceptions table once each with a leading
  `Component` column; the Storybook story lists with their cells; then §A, the `16` §12 design-QA
  checklist, and §B, the `05` §10 template, for the eight screens.
@ prose
  The boards are PENDING: the Penpot page is `E27-D03 Accounts and key vault hi-fi`, named in spec
  §0 and referenced by name only until the boards step records its id.
@ prose
  Fixture values only; no key material, secret, real UID or real address appears anywhere.
§ hand-off ‖ Handoff checklist — CMP-175 KeyPermissionBadge (
@ heading
  ## Handoff checklist — CMP-175 KeyPermissionBadge (E27-D03, #816)
@ prose
  - [ ] **Final Penpot link** — PENDING: page `E27-D03 Accounts and key vault hi-fi` (spec §0),
  boards 01 and 02 (its light twin); exports
  `docs/design/E27/img/E27-D03-01-cmp-175-key-states.png` and
  `docs/design/E27/img/E27-D03-02-cmp-175-key-states-light.png` with their greyscale, deuteranopia
  and protanopia renders, all in the boards PR; no board exists yet
@ prose
  - [x] **Variants × States matrix** — thirteen states in the `key` scope (`badge` and `inline`
  forms) and the `aggregate` line's eight forms, each with its served source, class, glyph and
  word (spec §2.1); Table 1
@ prose
  - [x] **Live data** — no live region of its own: the host's shell announcer speaks a key's
  failure once, assertive, and a recovery polite; the aggregate line's negated forms stay silent
  while CMP-092's blocking row speaks (`15:935`; spec D03-C9); Table 5
@ prose
  - [x] **Motion pair** — none animated: a state changes by an instant token swap; any motion is
  E27-D04's (spec D03-H1); Table 4
@ prose
  - [x] **Tokens used** — fills `color.status.success.subtle`, `color.status.danger.subtle`,
  `color.status.warning.subtle`, `color.status.info.subtle`, `color.neutral.subtle`; words
  `color.text.primary`, the critical one `font.weight.bold`; glyphs `color.status.success.strong`,
  `color.status.danger.strong`, `color.status.warning.strong`, `color.status.info.strong`,
  `color.text.secondary`; the critical border `border.thick` in `color.status.danger.strong`;
  `size.icon`, `space.inset.xs`, `type.ui.caption`, `type.ui.body`, `radius.badge`; Penpot token
  sets = `packages/ui/tokens` at `e8bca4bb7` (spec §2.1, §9)
@ prose
  - [x] **Data contract confirmed** — `KeyVerification` (`withdraw_enabled`, sent only once the
  rights were read), `KeyVerificationNotRead`, `ApiKey` (`read_only`, `expires_at`,
  `last_verified_at`), the security summary's `keys[]` (`withdrawal_permission_present`,
  `ip_whitelist_matches_expected`) and the `system` read-only notices for the aggregate forms
  (spec §2.1); gaps: G-1 (per-row attribution, #895 / #896), G-2 (the verdict's time) and D03-G1
  (the egress IP before a check, #896)
§ hand-off ‖ Handoff checklist — CMP-176 AccountKeyRow (E27-D
@ prose
  - [ ] **Final Penpot link** — PENDING: page `E27-D03 Accounts and key vault hi-fi`, boards 03
  (the rows, blocked, both disabled forms, the 200 % card) and 04 with its light twin 05
  (SCR-125's records); exports `docs/design/E27/img/E27-D03-03-components-and-looks.png`,
  `docs/design/E27/img/E27-D03-04-scr-125-128-accounts.png` and
  `docs/design/E27/img/E27-D03-05-scr-125-128-accounts-light.png`, in the boards PR
@ prose
  - [x] **Tokens used** — the row `color.surface.raised`, hover `color.surface.hover`; line 1
  `color.text.primary`, line 2 and the notice `color.text.secondary`; the label
  `type.ui.body-strong`, numbers `type.num.base`; blocked `color.status.danger.subtle` with a 4 px
  `color.status.danger.strong` inline-start rule; rows apart `border.hairline` in
  `color.border.default`; focus `color.focus.ring` with `border.focus`; the environment badge
  `color.env.live` or `color.env.demo`; details links `color.text.link`; Penpot token sets =
  `packages/ui/tokens` at `e8bca4bb7` (spec §2.2, §9)
@ prose
  - [x] **Data contract confirmed** — `listExchangeAccounts` (`AdminAccountRow`: label, UID,
  environment, kind, `key_status`, `health`, `enabled`), `listApiKeys` (the key's metadata),
  `getSecuritySummary`'s `keys[]` for the facets and `AccountHealth` (spec §3.3); gaps: G-1
  (per-row attribution, #895 / #896), D03-G2 (the off-by-policy state, #895) and G-12 (the re-arm,
  #3657)
§ hand-off ‖ Handoff checklist — CMP-034 MaskedValue (E27-D03
@ heading
  ## Handoff checklist — CMP-034 MaskedValue (E27-D03, #816)
@ prose
  - [ ] **Final Penpot link** — PENDING: page `E27-D03 Accounts and key vault hi-fi`, board 01
  (the masked id beside CMP-175's set) and every screen board that names a key; exports in the
  boards PR
@ prose
  - [x] **Variants × States matrix** — one state, masked, in four hosts (a row, a dialog, a table
  cell, with its description) and forced colours; no reveal, timer or copy state exists (BQ-8,
  RULED; spec §2.3); Table 1
@ prose
  - [x] **Accessible name / role table** — `role="group"` named by `label`; the `...` behind a
  visually hidden "ending in", so it reads "API key, ending in a1b2"; the write-only description,
  one node per page in the DOM at mount, named by every instance's `aria-describedby` (spec §2.3);
  Table 3
@ prose
  - [x] **Tokens used** — `type.num.base` in `color.text.primary` on its host's surface
  (`row-text` on a row, `dialog-text` in a dialog or the drawer); no box, so no fill, border or
  radius; Penpot token sets = `packages/ui/tokens` at `e8bca4bb7` (spec §2.3, §9)
@ prose
  - [x] **Data contract confirmed** — `ApiKey.key_id_masked`, `...` plus 4 characters, the rest
  never stored in clear; any other value renders nothing (spec §2.3; `22:16879-16882`); the masked
  id is the only key value any response carries (C-2.7, C-12.2)
@ prose
  - [ ] **Sign-off** — owner approval pending; the supersession of E05-D02's time-limited display
  stays the owner's (spec D03-C4, D03-A3), and no board draws a reveal meanwhile
§ hand-off ‖ The extended entries — one delta row each
@ head 8
  Tokens
@ row CMP-178 SystemHealthTile ‖ Name / role
  plain text in its cell: no region, heading or link
@ row CMP-178 SystemHealthTile ‖ Tokens
  the word `color.text.primary`, the age `color.text.secondary`, the glyph in its tone's strong
  token
@ row CMP-201 PasswordField ‖ Entry
  CMP-201 PasswordField
@ row CMP-203 RequirementChecklist ‖ Live data
  `live={false}` for the key gate: its host announces the verdict once
@ row CMP-033 CopyButton ‖ What changes (spec §)
  the egress IP as the key screens' only copy, never a key id, UID or secret (§2.3)
§ hand-off ‖ Table 1 — Variants × States
@ row CMP-175 ‖ Component
  CMP-175
@ row CMP-175 ‖ Variant
  `key` · `badge`
@ row CMP-175 ‖ State (each a named fram
  verified, trade-only, read-only (stored), withdrawal-detected (critical), IP-missing,
  IP-mismatch, expiring, expired, not checked, check overdue, allowlist matches, allowlist not
  checked; read-only at import is the check list's failed row
@ row CMP-175 ‖ Penpot variant (planned)
  `CMP-175 · KeyPermissionBadge / Scope=key, Form=badge, State=…`
@ row CMP-175 ‖ Story (planned)
  `Atoms/KeyPermissionBadge/*`
@ row CMP-175 ‖ Component
  CMP-175
@ row CMP-175 ‖ Variant
  `key` · `inline`
@ row CMP-175 ‖ Penpot variant (planned)
  `… / Scope=key, Form=inline, State=…`
@ row CMP-175 ‖ Notes
  CMP-176's facet cells, SCR-128's table, SCR-079's key block
@ row CMP-175 ‖ Component
  CMP-175
@ row CMP-175 ‖ State (each a named fram
  dated, overdue, failed, unavailable, read failed, no keys, loading, cleared
@ row CMP-176 ‖ State (each a named fram
  OK, rotating, revoked, blocked, key refused, expired at Bybit, allowlist no match, allowlist
  none set, down, off by policy, check overdue, not checked, rotation overdue, degraded, rotation
  due, Bybit expiry, no key, disabled; KEK unavailable; menu open, details open, hover,
  focus-visible; 200 % card, 150 % text, compact at 125 %
@ row CMP-034 ‖ Component
  CMP-034
@ row CMP-034 ‖ Variant
  masked, its only state
@ row CMP-034 ‖ State (each a named fram
  on a row, in a dialog, in a table cell, with its description; a non-masked value renders
  nothing; forced colours
@ row CMP-034 ‖ Penpot variant (planned)
  `CMP-034 · MaskedValue / Host=…`
@ row CMP-034 ‖ Story (planned)
  `Atoms/MaskedValue/*`
@ row CMP-034 ‖ Notes
  spec §2.3; no reveal, timer or copy exists
§ hand-off ‖ Table 2 — Keyboard
@ head 2
  Key
@ row CMP-175 ‖ Component
  CMP-175
@ row CMP-175 ‖ Notes
  the row's actions carry the keys
@ row CMP-034 ‖ Component
  CMP-034
§ hand-off ‖ Table 3 — Accessible name / role
@ row CMP-175 ‖ Component
  CMP-175
@ row CMP-175 ‖ Accessible name (source)
  its word, e.g. "BLOCKED — fund right found"
@ row CMP-175 ‖ Component
  CMP-175
@ row CMP-175 ‖ Accessible name (source)
  its sentence, e.g. "Withdrawal: OFF on all 4 accounts with a key ✓ · verified 14:02 UTC"
@ row CMP-034 ‖ Component
  CMP-034
@ row CMP-034 ‖ Element
  the masked id
@ row CMP-034 ‖ Accessible name (source)
  "API key, ending in a1b2"
§ hand-off ‖ Table 4 — Motion pair
@ head 5
  Duration / easing tokens
@ row CMP-175 ‖ Component
  CMP-175
@ row CMP-175 ‖ motion-safe
  instant token swap
@ row CMP-034 ‖ Component
  CMP-034
§ hand-off ‖ Table 5 — Live data
@ row CMP-175 ‖ Component
  CMP-175
@ row CMP-175 ‖ Field
  a key's state turning failed, critical or down
@ row CMP-175 ‖ Component
  CMP-175
@ row CMP-175 ‖ Component
  CMP-175
@ row CMP-176 ‖ Politeness
  through the shell announcer, as CMP-175
@ row CMP-034 ‖ Component
  CMP-034
§ hand-off ‖ Density
@ head 4
  Padding tokens
@ row CMP-175 ‖ Component
  CMP-175
@ row CMP-175 ‖ Component
  CMP-175
@ row CMP-034 ‖ Component
  CMP-034
§ hand-off ‖ Storybook stories × themes × densities
@ row CMP-175 ‖ Component
  CMP-175
@ row CMP-175 ‖ Stories (spec §13)
  Default · WithdrawalVerified · WithdrawalDetected · WithdrawalNotChecked ·
  WithdrawalCheckOverdue · RightsTrade · RightsMissingScopes · RightsReadOnly · AllowlistMatches ·
  AllowlistNoneSet · AllowlistNoMatch · AllowlistNotChecked · ExpiryExpiring · ExpiryExpired ·
  InlineForm · AggregateDated · AggregateOverdue · AggregateFailed · AggregateUnavailable ·
  AggregateReadFailed · AggregateNoKeys · AggregateLoading · VariantSet · MissingStateNeverOff ·
  ForcedColors
@ row CMP-034 ‖ Component
  CMP-034
@ row CMP-034 ‖ Stories (spec §13)
  Default · InDialog · InTableCell · WithDescription · NonMaskedValueRendersNothing · ForcedColors
@ row CMP-201 (`writeOnly`) ‖ Component
  CMP-201 (`writeOnly`)
§ hand-off ‖ A. Design QA checklist (`16` §12) — SCR-125..129
@ prose
  - [x] Only published Tier-2 and Tier-3 tokens: the spec binds names, never a hex; every
  unpublished name is marked — DS-3's alias bound to `color.text.tertiary` until it lands,
  CMP-015's skeleton name (spec D03-C12) and `15`'s non-token names, each replaced by an A-row
  (spec §9, Appendix A).
@ prose
  601 luma, for every CMP-175 class (spec §9); the greyscale, deuteranopia and protanopia renders
  of boards 01 and 02 come with the boards PR (BQ-16).
@ prose
  - [x] Disabled states use the disabled-with-reason pattern (CMP-079) — the one rule, view-as
  first (spec §10.1), with ten PROPOSED E27 reason keys (spec §12.2); busy, outcome, availability,
  the validity look, T4, T1 and T3 stay apart (spec §10.3).
@ prose
  - [x] Confirm-gate variant stated — revoke rung 1 with the `keys` step-up, or rung 3 with the
  typed label for an account's last active key; disable and delete rung 3 with the typed label,
  their step-up class stamped "not yet served — G-8, #895 / #898"; rotate rung 1 with the `keys`
  step-up; each keyboard path in spec §7, §11.
@ prose
  - [x] Every heuristic or estimated value is chip-tagged — E27 shows none; a stale balance is
  CMP-239's chip with its time (frame 66).
§ hand-off ‖ B. Accessibility acceptance criteria (`05` §10)
@ code
  Feature: E27-D03 accounts and key vault — accessibility acceptance criteria
@ code
  When the Owner adds a key on SCR-126, rotates it on SCR-127 and revokes it on SCR-129
@ code
  Then every control involved is reachable via Tab/arrow-key navigation (SCR-125's records
@ code
  When the Owner reads SCR-125 and tests a key
@ code
  LIVE" as the row header, "Withdrawal OFF ✓ · verified 14:02 UTC" as words, "API key,
@ code
  05-accessibility-standard.md §6.2, without flooding (a failed key assertive once through
@ code
  When a CMP-175, CMP-011 or CMP-178 state is rendered
@ code
  non-text UI/chart elements meet >=3:1, per the token contrast matrix (spec §9: 57 gated
@ code
  Given a T2 control (Rotate key… while the KEK is unavailable, the leave-positions radio
"""


# --- the pinned confirm-look text (§7e): ``--repin-confirm-look`` prints it; a reviewer reads it --
CONFIRM_LOOK_PINS = r"""
§ spec ‖ E27-D03 — Accounts and key vault hi-fi and desig
@ prose
  **Revision:** r11 — r10's re-check folded (§16 items 10 and 11): a frame row, a §2.4 row and a
  prose paragraph that name the load are read whole for the confirm, each sentence up to where it
  moves past the load; the exit check reads a bare Esc and Cancel in any case, and also reads
  §2.4's cells and the spec's prose; r10 — the default-deny pin's re-check folded (§16 items 10,
  11 and 13): `k4.loading` and `k9.exit` read the gated words (disabled, dimmed, greyed or grayed
  out, inactive, inert, locked, held, hidden, unavailable, unusable, suppressed, no effect) on
  either side of the confirm or the exit, the appositive ", visible but inactive" included, and a
  token, a password, a balance and "shown in full" make a clause security-bearing; r9 — the
  orchestrator's text round 3 folded as a default-deny pin (§16 item 13): every clause of this
  spec and the hand-off that names a key, a secret, a credential, a fund or money word, a reveal
  or mask word, plain or clear text or CMP-034, CMP-175 or CMP-201, and every statement of the
  view-as leg, equals one entry of the audit tool's pinned table, so security text that is new,
  changed, moved or duplicated fails `sec-pin` until a reviewer reads it there; the word list
  decides which clauses are pinned, and the table what a pinned clause may say; r8 — the
  orchestrator's text round 3 folded into the audit tool (§16 items 10–12): every line is read for
  a bare id, a show, view, copy or toggle of a key or a secret, a visibility toggle, a bracketed
  control that is not the egress IP's copy and a fund right in the modal form ("can withdraw"),
  with no key named on the line; a table row's withdrawal word ties an OFF in any of its cells to
  its time; a view-as frame's class says "view-as leg first"; r7 — the orchestrator's text round 2
  folded into the audit tool (§16 item 12): K1, K2, K3, the dated OFF and the reveal words read
  every clause of every line of this spec and the hand-off, case-insensitive, with no section
  list, and a hit passes only inside a pinned, counted allow-list of exact phrases; a gated frame
  that E27-D02's inventory or its class names as a view-as frame leads with `rbac.view_as`; r5 —
  the orchestrator's text round 1 folded into the audit tool (§16): K1–K3 read every clause of
  every frame row and the secret-field rows outside the frames (§2.3, §4.1, §5) for a bare id and
  a show, copy or toggle control, a withdrawal control, and a withdrawal "OFF" without its time;
  no `lock` on a frame that is not gated; a view-as row of §10.2 leads with its view-as leg; the
  confirm never drawn while the summary loads; an exit gated after a comma; E42-D03's boards PR
  never pinned or quoted; the environment gate reads every frame that names one; and the check
  list's fresh-pass "OFF ✓" dated (D03-C15); r4 — re-pinned at its PR base `e8bca4bb7` (every
  moved `file:line` re-mapped and re-read), and Appendix A's CMP-028 and CMP-044 rows re-based on
  #4414's rewrite of those entries (D03-C16; CMP-015's skeleton token, D03-C12, resolved
  upstream); r3 — the audit tool's gates read each frame row (the standing rule A2's K1–K15, §16),
  each with its own `--self-test` mutation, and the rows that named an element only by reference
  now carry it (§16); r2 — the security and design lens round 1 folded: every withdrawal "OFF"
  dated (D03-C15), the drawer's critical state a badge, the check list's warnings on the triangle
  (HD17), the Enable… dialog, the held step-up request's unanswered re-send, the link on the
  drawer measured, and the audit tool's mirror mutation and OFF gate; r1 — the full text on r0's
  skeleton and audit tool: §1–§17, Appendix A's copy-ready A-rows and the handoff file
  `docs/design/E27/E27-D03-handoff.md`; the boards and their exports follow in the boards PR.
§ spec ‖ The questions (BQ-1…BQ-16) and the defaults buil
@ row BQ-11 ‖ Default built
  consume E42-D03's unlanded rung props (`E42-D03:902-904`) by name, PROPOSED with a "contract
  pending" stamp until they land (the ruling), and add only: the consequence-summary loading
  state, with no confirm rendered, Cancel only, "Reading what sub_002 holds…" and "Still reading…"
  after 1 s (`D02:723-729`); the title's environment suffix (`D02:262-270`); the typed token, the
  account label or the server's `target` (`D02:266-267`); `Enter` in the typed field never
  confirms (D22); the ask line before the press, stamped "not yet served — G-8, #895 / #898" for
  disable and delete; the audit marker last (CMP-093, `E42-D03:691`); two radios, none checked,
  the stop-loss radio gated on `accounts.stop_missing` (D10); validity is E42-D03's model, the
  confirm `aria-disabled` and focusable with its hint in the validity look (D02 only allows native
  `disabled`, `D02:1027-1039`); every A-row reads "if E42-D03's boards PR lands its Appendix A
  first, re-read and re-base" (GATE R6); OQ-9 and OQ-10 stay the owner's (#2701), drawn at their
  PROPOSED defaults
§ spec ‖ 0. The boards (PENDING; ten under the lever-4 ca
@ row 07 ‖ Frames (E27-D02 §7)
  `SCR-127 / stage 1: create the new key at Bybit`; `SCR-127 / stage 2: paste and confirm`;
  `SCR-127 / stage 3: verifying, elapsed time per stage`; `SCR-127 / stage 3 refused: nothing
  changed, the old key still active`; `SCR-127 / stage 3 no verdict: nothing changed`; `SCR-127 /
  stage 4: switched, the 900 s overlap`; `SCR-127 / stage 5: old key revoked here, delete it at
  Bybit`; `SCR-127 / not yet served: drain read, rollback, early revoke, failed`; `SCR-127 / KEK
  unavailable: Rotate is T2`
§ spec ‖ 1.2 The hi-fi decisions (HD1…HD17)
@ row HD8 ‖ Alternative (why not)
  (a) native `disabled` (E27-D02's allowance): two validity models on one ladder; (b) a 2 px
  confirm border: the 2 px border belongs to the critical mark and the blocking notice; (c) Cancel
  first in the DOM: the DOM would not follow the footer's visual order
§ spec ‖ 2.4 The extensions — CMP-028, CMP-035, CMP-044,
@ row CMP-044 ConfirmDialog (Molecule): typed ‖ Current (`15`)
  `variant` (standard, typed, hold) · `typedConfirmValue?` · `role?` · `restatement?` ·
  `confirmDelayMs?` · `autoCancelMs?` · `busy?` (`15:476`); the typed Confirm natively disabled
  until the summary loads and the field matches (`15:477`); Cancel first, the hold variant's
  keyboard path and `Enter` in the typed field never confirming (`15:478`); the destructive
  Confirm a solid CMP-001 `danger` (`15:479`); its purpose says "delete API key" (`15:475`)
@ row CMP-044 ConfirmDialog (Molecule): typed ‖ Gap
  no consequence-loading state (no confirm may render until the summary loads, `14:2576`); no
  environment in the title; no rung, choice, ask line or marker until E42-D03's props land; a key
  is revoked here and never deleted at Bybit (`22:2847-2851`); the solid `danger` confirm's label
  is under the 7.0 hc-text bar (§9 `c175-solid-danger`), and a natively disabled confirm is not
  E42-D03's validity form (D03-C11, D03-C16)
@ row CMP-044 ConfirmDialog (Molecule): typed ‖ Proposed: props · a11y ·
  E42-D03's `rung`, `blastRadius`, `choices`, `stepUpState` and `auditCodes` consumed by name,
  PROPOSED, contract pending (`E42-D03:902`); its `acknowledge`, the `positions_unknown` tick, is
  never rendered on an E27 dialog: revoke, disable and delete take no acknowledge parameter
  (`22:14561-14564`), and the dead and fixable remedies are frame 56's resend and Close · +
  `consequenceState?` (loading or ready) · `environment?` · a11y: the confirm absent while
  loading, E42-D03's validity form (`E42-D03:542`) in place of the native `disabled` · tokens: the
  destructive confirm on `color.status.danger.subtle` with a 1 px `border.hairline`
  `color.status.danger.strong` border in place of the solid fill, the title `type.ui.heading-md`
  (D03-C16) · + ConsequencesLoading, ConsequencesLoadingSlow, EnvironmentSuffix,
  TypedLabelEnterNeverConfirms, ConfirmValidityHint, TwoChoicesNoneSelected, GatedChoice,
  ExchangeError
§ spec ‖ 2.6 The cross-screen pattern frames (E27-D02 fra
@ row 4 ‖ Hi-fi (dark; light by to
  four gated controls in E09-D09's T2 form — a menu item ("Rotate key…" under
  `keys.kek_unavailable`), a button ("Verify and save"), a radio ("Leave positions and orders
  open" under `accounts.stop_missing`) and a checklist step (`rbac.owner_only`) — each with the
  `lock` leading its full label, `aria-disabled="true"` and its reason as the 2a second line,
  inside CMP-079 RbacGate; beside them an unmet rung confirm in E42-D03's validity form (no lock,
  no key) and the rejected dimmed look, drawn only as a struck-through specimen (§9 `t2-dimmed`);
  the ten PROPOSED E27 keys of §12.2 listed with their strings
§ spec ‖ 4.3 The hi-fi rows (frames 18–32)
@ row 30 ‖ Hi-fi: layout and redlin
  SCR-006 over frame 19, consumed from E09-D06 and never redrawn: the board draws frame 19 under a
  flat 60 % scrim (`opacity.scrim`, no blur) with SCR-006's footprint labelled "SCR-006 code-only,
  E09-D06" (`D06:16-17`, `D06:27-28`): `role="alertdialog"`, password and code fields (`D06:47`),
  focus on the password field; its title "Confirm it's you" and its description the server's
  `action_summary` verbatim, here in `22:14996`'s form for demo-1, "Import API key for account
  'demo-1' (demo, UID 9000001)" (`22:15977-16002`); the press is held unchanged and re-sent once
  on success (`22:11910-11919`; `D06:40`); a cancel, the expiry, the third failure, the idle lock
  (SCR-005) or the absolute session expiry drops it, with "Not saved — nothing was sent." and both
  secret fields cleared (KV-I10; `22:11915-11916`); a re-send that gets no answer (a network error
  or a timeout) may have stored the key, so the card never says "Not saved" and never sends again:
  it shows `e27.shared.resend_unconfirmed`, reads the key list back (`listApiKeys`) and shows what
  it finds — the key listed, frame 21's result with both fields cleared; not listed, nothing was
  stored and the fields stay for a new Verify and save (`22:11915-11919`); inside the 5-minute
  `keys` grace no dialog opens and the ask line reads "Still trusted for key changes · 02:14"
  (`22:11921-11924`)
§ spec ‖ 5. SCR-127 — Key rotation (board 07)
@ row 34 ‖ Hi-fi (dark; light by to
  Stepper: 1 done, 2 current. `h2` "Paste the new key". Before the fields, the consequences of the
  press: RA-1's lead, "Open orders stay open. Both keys work for 15 minutes while requests
  drain.", and "Then the old key ...e5f6 is revoked here. There is no undo: to go back, rotate
  again." (PROPOSED: OQ-10's line, `D02:577`, moved before the confirm so the rung states what it
  cannot undo first). The two write-only fields, the ask line, the marker; footer [Cancel] [Back]
  [Verify and switch] — the destructive confirm, rung 1, enabled at once; an empty field shows its
  inline error on the press (`D02:1033-1035`). Without a live grace the press opens SCR-006 over
  the wizard (T1; E09-D06's chassis, consumed and never redrawn; password and code; its
  description the server's `action_summary` verbatim, which names sub_002 with LIVE and UID
  1234569, `22:11857-11863`); the held request is re-sent once on success; Cancel, expiry, a third
  failure, the idle lock (SCR-005) or the absolute session expiry reads "Not saved — nothing was
  sent." and clears both fields (`D02:530-531`; `22:11915-11916`); a re-send that gets no answer
  may have rotated the key, so the wizard never says "Not saved" and never sends again: it shows
  `e27.shared.resend_unconfirmed`, reads the key list back (`listApiKeys`) and shows what it finds
  — the old key `rotating`, the switch happened (stage 4), or still `active`, nothing changed
  (stage 2) (`22:11915-11919`). Board 07 draws stage 2 and, inset, SCR-006 over it. Focus: the
  `h2`; Tab New API key → New API secret → Cancel → Back → Verify and switch.
§ spec ‖ 7. SCR-129 — Disable, delete and the revoke dial
@ row Footer ‖ Content and copy
  [Cancel] first and initially focused, then the confirm. The confirm is absent from the DOM until
  the summary has loaded; never auto-focused; it ignores `event.repeat`; while a choice or the
  typed label is unmet it is `aria-disabled`, focusable and in the validity look with its hint (no
  lock, no CMP-079, never T2), and `Enter` or `Space` on it moves focus to the first unmet input
@ row 49 ‖ Hi-fi (dark; light by to
  Opened from "Revoke key…" on sub_002's row while ...d9e0 is also active: title "Revoke key
  ...e5f6 on sub_002 · LIVE"; the consequence, "It stops working here at once; sub_002 keeps
  trading on ...d9e0. It still works at Bybit until you delete it in Bybit's dashboard." — CP-4's
  two clauses together, as H6 asks (`MEMO:194`); no choices, because another active key remains
  and the account keeps trading (`22:2854-2860`); no typed label (rung 1); the ask line (served)
  and the marker; [Cancel] [Revoke key ...e5f6 here], the confirm rendered and enabled at once.
  Without a live grace the press opens SCR-006 (T1), the request held and re-sent once
  (`22:11851-11863`); a re-send that gets no answer may have revoked the key, so the dialog never
  says it was not sent and never sends again: it shows `e27.shared.resend_unconfirmed`, reads the
  key list back (`listApiKeys`) and shows frame 52's outcome on a `revoked` key, or the key still
  active (`22:11915-11919`). Focus: Cancel; `Esc` cancels; focus returns to "Actions for sub_002 ·
  LIVE".
@ row 51 ‖ Hi-fi (dark; light by to
  As frame 50, but the summary shows BTCUSDT long 0.250 with `native_stop_present: false`: its
  line leads with the octagon, "BTCUSDT long 0.250 — no stop-loss", and the list adds "BTCUSDT
  long 0.250 has no stop-loss; once the key is gone nothing could add one. Add its stop first, or
  choose Flatten first." "Leave positions and orders open" keeps its place, its role and its full
  label, T2 per §10.1: the `lock` leads it, `aria-disabled="true"`, its second line "Refused while
  a position has no stop-loss." (`accounts.stop_missing`, 2a; carried by CMP-044's
  `choices[].disabledReason`, CMP-079 once the key is registered, E42-D03:903); an arrow onto it
  focuses it without checking it, `Space` re-shows the reason with one polite announcement, and it
  emits nothing; "Flatten first — …" stays available, and the T2 choice can never enable the
  confirm. A `409 open_exposure` after a stale read shows the same refusal at the point of action
  (T4; `22:14505-14509`; #2903). The disable dialog's choice takes the same T2 (`D02:761-762`).
@ row 61 ‖ Hi-fi (dark; light by to
  Disabled: sub_002's SCR-125 row reads "Disabled at 14:12 UTC — doesn't trade here." with
  [Enable…] in the place of "Disable…" (an outcome, never T2; #960 Q13; `D02:750-751`), at full
  text contrast and never dimmed (BQ-7; C-10, `D02:1205`). [Enable…] opens a rung-1 CMP-044 dialog
  that is not destructive: "Enable sub_002 · LIVE", its one consequence "Its rules stay disarmed
  until you arm them by hand.", the ask line as a target state stamped "not yet served — G-8, #895
  / #898", the marker "Recorded in the audit log" with no code (`24:4854` names `account.disabled`
  and no enable), then [Cancel] [Enable sub_002], the confirm a CMP-001 primary; it sends
  `updateExchangeAccount` with `enabled: true` (`accounts:write`; `22:2592-2631`), and whether
  that write records `accounts.enable_trading` (`ACT:135`) is D03-Q4. Deleted: the row leaves the
  list, and a notice under the `h1` reads "sub_002 · LIVE deleted — history kept. Its keys still
  work at Bybit until you delete them there." (polite once; `D02:752-753`, `D02:270`). Focus after
  a disable returns to the row's Actions button; after a delete, whose opener is gone, it moves to
  the notice (`tabindex="-1"`; PROPOSED).
@ row 61 ‖ Copy keys
  `e27.scr125.outcome.disabled` · `e27.scr125.menu.enable` · `e27.scr129.enable.title` ·
  `e27.scr129.enable.rules` · `e27.shared.ask` · `e27.scr129.marker` · `e27.scr129.enable.confirm`
  · `e27.shared.cancel` · `e27.shell.notice.deleted`
§ spec ‖ 9. Contrast, greyscale and colour vision — the m
@ prose
  **E30-D02's dimmed validity look** (composite; reported, never gated): the label of an unmet
  primary confirm at `opacity.disabled` 0.45 <!-- audit:numbers.opacity_disabled=0.45 --> over its
  own dimmed fill on a dialog measures dark 3.30 <!-- audit:composite.dark=3.30 -->, light 1.46
  <!-- audit:composite.light=1.46 --> and high contrast 1.72 <!--
  audit:composite.high-contrast=1.72 -->.
@ prose
  That is why no E27 frame draws it: CMP-044's unmet confirm takes E42-D03's validity form instead
  (§2.4, §10.3; BQ-11) — its fill `color.surface.raised` with a `color.border.default` hairline
  and its label `color.text.tertiary`, the `t2-label` pair — and its hint sentence in full-opacity
  `color.text.secondary` carries the meaning; the T2 binding never dims (`t2-dimmed`, rejected).
§ spec ‖ 10.3 What is NOT T2
@ prose
  - **The validity look** — form validity, E42-D03's form for a rung confirm (`E42-D03:542`,
  `E42-D03:566-567`), adopted for CMP-044 by BQ-11 in place of E30-D02's dimmed look
  (`E30-D02:128`): a rung-3 confirm before the summary has loaded is not rendered at all (Cancel
  only); after it, until the typed label matches and, where there are two, a radio is chosen, the
  confirm stays focusable with `aria-disabled`, its danger fill dropped to `color.surface.raised`
  with a `color.border.default` hairline, its label `color.text.tertiary` and its hint in
  full-opacity `color.text.secondary` under it — no lock, no CMP-079, no key (layer
  `validity-reason`); empty key fields show an inline error on press (CMP-040).
§ spec ‖ 14. A, C, G and H rows, deviations and questions
@ row D03-C11 ‖ Row
  **The unmet rung confirm.** E27-D02 allows a native `disabled` confirm (`D02:1033-1034`);
  E42-D03 keeps it focusable in its validity form (`E42-D03:542`). **Decision:** E42-D03's
  validity form, so one ladder has one model (HD8; §10.3).
@ row D03-C16 ‖ Row
  **#4414's CMP-028, CMP-043 and CMP-044 lines** (E05-D02 slice 4, merged after E27-D02's base).
  (1) CMP-044's Tokens bind the destructive Confirm as a solid CMP-001 `danger`, whose label is
  under the 7.0 hc-text bar (§9 `c175-solid-danger`; the BQ-6 rider in §2.1); (2) its typed state
  keeps the Confirm natively `disabled`, where D03-C11 takes E42-D03's focusable validity form;
  (3) CMP-043's title is `type.ui.heading-sm`, where §2.4 binds `type.ui.heading-md`; (4) CMP-028
  gained `placement`, `live` and `edge`, and `live="off"` is half of `blocking`. **Decision:**
  Appendix A is re-based on #4414's text and changes only these four points: E27's destructive
  confirm on `color.status.danger.subtle` with its `color.status.danger.strong` hairline, the
  validity form, `type.ui.heading-md`, and `blocking` defined as `live="off"`, never dismissible
  and an `id`; every other #4414 addition is kept as written. The boards PR re-reads this row
  before it draws the confirm or the notice.
§ spec ‖ 16. Traceability and the audit tool's checks
@ prose
  K1: no control that shows or copies key material — a `[Show]`, a Show toggle, a `[Copy]` or a
  copy control whose nearest cue is a key or a secret field rather than the egress IP — no key id
  but `...` plus 4, no bare id (eight or more letters and digits, both present) and no
  plaintext-like value (a 16+ character run with two digits or short mixed-case segments, or a key
  value with a digit or an inner capital); K2: no reveal prop or state (item 12); K3: no
  withdrawal or transfer right drawn as allowed or as a toggle, switch or checkbox, and every
  withdrawal "OFF" a frame draws carries "verified" and its time in the same string or item
  (`k3.off`); K4 and K5: each destructive confirm (frames 5, 34, 49–51, 54–56, 58 and 59: 10 <!--
  audit:numbers.frames_destructive=10 --> in all) names its consequence key and the ask line
  `e27.shared.ask` in its Copy keys, both in §12, and its Hi-fi cell draws them — the
  consequence's §12 string with its placeholders filled, the ask line and, where its keys list
  `e27.scr129.typed`, the typed label (a row opening "As frame N" or "Frame N's dialog" inherits
  them from frame N); §7's confirms table states both, and no other frame draws a destructive
  confirm, and while the summary loads no frame, §2.4 cell or prose paragraph draws the confirm
  rendered, drawn, shown, visible or present, or with a gated word — disabled, `aria-disabled`,
  dimmed, greyed or grayed (out), inactive, inert, locked, held, hidden, unavailable, unusable,
  suppressed, no effect — before it ("a disabled confirm", "a greyed-out confirm") or after it
  anywhere in its sentence, across a semicolon, a dash, a cell and a parenthesis, so "it" carries
  the subject ("the confirm, visible but inactive"); a frame row, a §2.4 row or a prose paragraph
  (§16 and the revision line aside) that names the load is read whole, so a bare "A disabled
  confirm." on frame 53 fails, each sentence up to where it moves past the load ("after it", "once
  the summary has loaded", "when the summary arrives": the ready dialog's validity look, §10.3)
  (`k4.loading`); K6 to K8: each of the 20 <!-- audit:numbers.frames_t2=20 --> gated frames names
  the `lock` and CMP-079 RbacGate (§10.1's components) and a reason key a §10 or §12 table gives,
  `rbac.view_as` first wherever it appears and never put after another leg in the row's prose, no
  frame that is not gated draws a `lock` or CMP-079, a frame E27-D02's inventory or its name calls
  a view-as frame says "view-as leg first" in its class, and every §10.2 control the view-as
  session reaches as T2 `rbac.view_as` (its "Who sees what" row) lists the view-as leg first
  (`t2.viewas`); K9: no exit (Cancel, Close, Back, Esc with or without backticks) drawn gated, in
  a frame, a §2.4 cell, a prose paragraph (§16 and the revision line aside) or in §10.2, by the
  same gated words — after the exit in a parenthetical such as "(disabled)", after a verb, after a
  comma or a two-word appositive (", visible but inactive"), or carried by "it" or "which" later
  in the sentence, and before it ("a disabled [Cancel]", "an inactive CANCEL", "an unavailable
  Esc"; Cancel and Esc in any case there, Close and Back in Title or UPPER case or in brackets);
  K10: gate 2's word and glyph per state (`ac2.*`); K11: frame 46's steps, their keys and their
  deck strings in C-12.12's order (freeze, delete at Bybit, revoke, rotate the KEK, replace); K12:
  each of the 19 <!-- audit:numbers.frames_env=19 --> frames that names an environment, whose
  title or heading names an account, or that draws an "Attention:" strip string, keeps its badge —
  derived from the rows, not a fixed list; K13: the number before every marker is the marker's
  value, and every two-decimal contrast or ΔE76 value carries a marker; K14 and K15: gate 4's
  `inv.missing` and `inv.board`; and E42-D03's boards PR, in flight, is named by its branch only —
  a sha or a quote beside it fails (`pin.inflight`).
@ prose
  **The self-test** (`--self-test`; `--selftest` too): a passing spec built in memory from the
  base files refuses 37 <!-- audit:numbers.mutations=37 --> mutations, each by its own code, and a
  spec on disk with no FAIL meets every one that applies to it; then the standing rule's list, one
  mutation per K-item and a second (or more) where a K-item reads more than one element or form,
  three for the in-flight pin, and item 12's record forms of the text round 2 — each in the
  section the round named and again in another, in lower and title case, an allowed phrase copied
  to a new place, Appendix A's States cell, frame 69's view-as leg cut from its prose or swapped
  for the role leg, and three on the hand-off; and round 3's forms — "view the full key" and
  "toggle visibility" on §6's Key cell, §8's owner key row, §4.1's block H, §2.5's CMP-034 row and
  frame 36 (lower, title and upper case), "can withdraw" on §6's Rights row, §8's owner key row,
  §4.4's block D and frame 36, a bare id, `[Show]` and `[Copy]` on §4.4's block D result row and
  in §4's and §8's prose, a deck string cut to "off ✓" and "Off ✓" and §2.1's verified row cut to
  "off ✓", frame 69's class naming the role leg, and three on the hand-off's CMP-033 row (a bare
  32-hex id, "Can Withdraw", "view the full key"); and the re-check's gated words — "a disabled
  confirm", "a dimmed confirm", "the confirm, visible but inactive", "a greyed-out confirm" and
  each gated word before and after the confirm, on frame 53 and in §2.4's `consequenceState`, and
  "a disabled [Cancel]", "[Cancel], visible but inactive" and each gated word before and after the
  exit, on frame 53 and frame 11; and its ten forms as a sentence of their own, in lower, Title
  and UPPER case — the confirm's on frame 53, in §2.4's `consequenceState` and in §7's prose, the
  exit's ("a disabled [Cancel]", "an inactive Cancel", "an unavailable Esc", "Close (locked)",
  "the [Close], hidden", "a disabled cancel", "a dimmed [Back]") on frame 53, in §2.4's
  `consequenceState` and in §2.4's prose — 338 <!-- audit:numbers.k_mutations=338 --> in all, each
  run in memory on this spec (or the hand-off) as a plain run: rc 1 with exactly one distinct
  FAIL, its own code, among the gates of items 1–12 (item 13's pin refuses it too wherever it
  edits pinned text); then item 13's 94 <!-- audit:numbers.pin_mutations=94 --> pin mutations;
  restored, `--check` exits 0 and the spec on disk is byte-identical (its sha256 compared).
§ spec ‖ Appendix A. The `15` and `14` edits, old → new
@ row CMP-044 · States (`15:477`) ‖ Old (verbatim)
  `… typed (Confirm natively disabled until the summary has loaded and the field matches exactly:
  form validity, not a gate);`
@ row CMP-044 · States (`15:477`) ‖ New
  ``… typed (Confirm absent from the DOM until the summary has loaded, then `aria-disabled` and
  focusable until the field matches exactly, E42-D03's validity form: form validity, not a gate;
  D03-C11, D03-C16);``
@ row CMP-044 · A11y (`15:478`) ‖ New
  ``… a gated Confirm keeps focus and announces once. The dialog is described by its first
  consequence; while the consequences load the confirm is absent from the DOM; until the label
  matches, or a choice is made, the confirm is `aria-disabled`, focusable and without a lock —
  form validity, not a gated control — its fill `color.surface.raised` with a
  `color.border.default` hairline and its label `color.text.tertiary`, described by the hint for
  the first unmet input, and `Enter` or `Space` on it moves focus there; a gated choice keeps
  `role="radio"`, `aria-disabled`, the CMP-019 `lock` glyph leading its label and its reason as
  its second line, inside CMP-079 RbacGate.``
"""


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
